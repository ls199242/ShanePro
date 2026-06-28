"""个人文档摄取和检索服务。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.document_chunker import split_document_text
from app.document_parser import DocumentParseError, parse_document, validate_supported_document
from app.rag_config import RagConfig, load_rag_config, normalize_psycopg_connection
from app.schemas import (
    DocumentDeleteResponse,
    DocumentSearchResponse,
    DocumentSearchResult,
    DocumentSummary,
    DocumentUploadResponse,
)
from app.vector_store import PgVectorDocumentStore, VectorStoreError


log = logging.getLogger(__name__)


class DocumentServiceError(RuntimeError):
    """文档服务运行时错误。"""


DOCUMENT_COLUMNS = """
    id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
    status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
"""

DOCUMENT_STATUS_UPLOADED = "uploaded"
DOCUMENT_STATUS_PARSING = "parsing"
DOCUMENT_STATUS_PARSED = "parsed"
DOCUMENT_STATUS_CHUNKING = "chunking"
DOCUMENT_STATUS_CHUNKED = "chunked"
DOCUMENT_STATUS_VECTORIZING = "vectorizing"
DOCUMENT_STATUS_READY = "ready"

INTERRUPTIBLE_DOCUMENT_STATUSES = {
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_PARSED,
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_CHUNKED,
    DOCUMENT_STATUS_VECTORIZING,
}
PROCESSABLE_DOCUMENT_STATUSES = {
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_PARSED,
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_CHUNKED,
    DOCUMENT_STATUS_VECTORIZING,
}


@dataclass(frozen=True)
class DocumentRecord:
    """数据库中的文档元数据记录。"""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    md5: str
    original_path: str
    parsed_text_path: str | None
    status: str
    chunk_count: int
    is_failed: bool
    error_message: str | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def to_summary(self) -> DocumentSummary:
        """转换为 API 文档摘要。"""
        return DocumentSummary(
            id=self.id,
            filename=self.filename,
            content_type=self.content_type,
            size_bytes=self.size_bytes,
            md5=self.md5,
            original_path=self.original_path,
            parsed_text_path=self.parsed_text_path,
            status=self.status,
            chunk_count=self.chunk_count,
            is_failed=self.is_failed,
            error_message=self.error_message,
            failed_at=self.failed_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class DocumentMetadataRepository:
    """PostgreSQL 文档元数据仓储。"""

    def __init__(self, config: RagConfig | None = None) -> None:
        self.config = config or load_rag_config()

    def init_schema(self) -> None:
        """初始化 pgvector 扩展和文档元数据表。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        id UUID PRIMARY KEY,
                        filename TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        size_bytes BIGINT NOT NULL,
                        md5 TEXT NOT NULL,
                        original_path TEXT NOT NULL,
                        parsed_text_path TEXT,
                        status TEXT NOT NULL,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        is_failed BOOLEAN NOT NULL DEFAULT FALSE,
                        error_message TEXT,
                        failed_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """,
                )
                cursor.execute("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS is_failed BOOLEAN NOT NULL DEFAULT FALSE")
                cursor.execute("ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ")
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET status = 'uploaded',
                        is_failed = TRUE,
                        error_message = COALESCE(error_message, '历史失败记录，请重新触发处理'),
                        failed_at = COALESCE(failed_at, updated_at),
                        updated_at = NOW()
                    WHERE status = 'failed'
                    """,
                )
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET status = 'parsing',
                        updated_at = NOW()
                    WHERE status = 'processing'
                    """,
                )
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_rag_documents_md5 ON rag_documents (md5)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag_documents (status)")

    def get_by_md5(self, md5: str) -> DocumentRecord | None:
        """根据 MD5 查询文档。"""
        return self._fetch_one(f"SELECT {DOCUMENT_COLUMNS} FROM rag_documents WHERE md5 = %s", (md5,))

    def get_by_id(self, document_id: str) -> DocumentRecord | None:
        """根据 ID 查询文档。"""
        return self._fetch_one(f"SELECT {DOCUMENT_COLUMNS} FROM rag_documents WHERE id = %s", (document_id,))

    def list_documents(self) -> list[DocumentRecord]:
        """查询所有文档。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {DOCUMENT_COLUMNS} FROM rag_documents ORDER BY created_at DESC")
                return [row_to_record(row) for row in cursor.fetchall()]

    def list_interrupted_documents(self) -> list[DocumentRecord]:
        """查询服务重启时遗留的运行中文档。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {DOCUMENT_COLUMNS}
                    FROM rag_documents
                    WHERE status = ANY(%s) AND is_failed = FALSE
                    ORDER BY created_at ASC
                    """,
                    (list(INTERRUPTIBLE_DOCUMENT_STATUSES),),
                )
                return [row_to_record(row) for row in cursor.fetchall()]

    def create_uploaded(
        self,
        document_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        md5: str,
        original_path: str,
    ) -> DocumentRecord:
        """创建等待处理的文档元数据。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rag_documents (
                        id, filename, content_type, size_bytes, md5, original_path, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'uploaded')
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (document_id, filename, content_type, size_bytes, md5, original_path),
                )
                return row_to_record(cursor.fetchone())

    def mark_stage_started(self, document_id: str, status: str) -> DocumentRecord:
        """标记某个处理阶段开始，并清理上次失败信息。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET status = %s,
                        is_failed = FALSE,
                        error_message = NULL,
                        failed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (status, document_id),
                )
                return row_to_record(cursor.fetchone())

    def mark_parsed(self, document_id: str, parsed_text_path: str) -> DocumentRecord:
        """标记文档解析完成。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET parsed_text_path = %s,
                        status = 'parsed',
                        is_failed = FALSE,
                        error_message = NULL,
                        failed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (parsed_text_path, document_id),
                )
                return row_to_record(cursor.fetchone())

    def mark_chunked(self, document_id: str, chunk_count: int) -> DocumentRecord:
        """标记文档切分完成。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET status = 'chunked',
                        chunk_count = %s,
                        is_failed = FALSE,
                        error_message = NULL,
                        failed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (chunk_count, document_id),
                )
                return row_to_record(cursor.fetchone())

    def mark_ready(self, document_id: str, chunk_count: int) -> DocumentRecord:
        """标记文档向量化完成。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET status = 'ready',
                        chunk_count = %s,
                        is_failed = FALSE,
                        error_message = NULL,
                        failed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (chunk_count, document_id),
                )
                return row_to_record(cursor.fetchone())

    def mark_failed(self, document_id: str, error_message: str) -> DocumentRecord:
        """标记当前处理阶段失败，保留 status 便于后续续跑。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rag_documents
                    SET is_failed = TRUE,
                        error_message = %s,
                        failed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, filename, content_type, size_bytes, md5, original_path, parsed_text_path,
                        status, chunk_count, is_failed, error_message, failed_at, created_at, updated_at
                    """,
                    (error_message[:1000], document_id),
                )
                return row_to_record(cursor.fetchone())

    def delete(self, document_id: str) -> None:
        """删除文档元数据。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM rag_documents WHERE id = %s", (document_id,))

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> DocumentRecord | None:
        """执行查询并返回单条记录。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row_to_record(row) if row else None

    def _connect(self) -> Any:
        """创建 psycopg 连接。"""
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise DocumentServiceError("缺少 psycopg 依赖，无法连接 PostgreSQL") from exc

        try:
            return psycopg.connect(
                normalize_psycopg_connection(self.config.pgvector_connection),
                row_factory=dict_row,
                connect_timeout=5,
            )
        except psycopg.Error as exc:
            raise DocumentServiceError("连接 PostgreSQL 失败，请检查 RAG_PGVECTOR_CONNECTION 配置") from exc


class DocumentService:
    """个人文档摄取、检索和删除服务。"""

    def __init__(
        self,
        config: RagConfig | None = None,
        repository: DocumentMetadataRepository | None = None,
        vector_store: PgVectorDocumentStore | None = None,
    ) -> None:
        self.config = config or load_rag_config()
        self.repository = repository or DocumentMetadataRepository(self.config)
        self.vector_store = vector_store or PgVectorDocumentStore(self.config)
        self._active_ingestions: set[str] = set()

    async def upload_document(self, file: UploadFile) -> DocumentUploadResponse:
        """上传文档并保存元数据，处理流程由用户手动触发。"""
        filename = Path(file.filename or "").name
        if not filename:
            raise ValueError("文件名不能为空")
        validate_supported_document(filename)

        try:
            content = await file.read()
            if not content:
                raise ValueError("上传文件不能为空")

            md5 = calculate_md5(content)
            self.repository.init_schema()
            existing = self.repository.get_by_md5(md5)
            if existing:
                return upload_response(existing, duplicate=True)

            document_id = uuid4().hex
            original_path = self._save_original_file(document_id, filename, content)
            content_type = file.content_type or "application/octet-stream"
            record = self.repository.create_uploaded(
                document_id,
                filename,
                content_type,
                len(content),
                md5,
                str(original_path),
            )
            return upload_response(record, duplicate=False)
        finally:
            await file.close()

    def process_document(self, document_id: str) -> DocumentSummary:
        """手动触发文档处理，并立即返回当前处理状态。"""
        self.repository.init_schema()
        record = self.repository.get_by_id(document_id)
        if record is None:
            raise ValueError("document not found")
        if record.status == DOCUMENT_STATUS_READY:
            return record.to_summary()
        if record.id in self._active_ingestions:
            return record.to_summary()
        if record.status not in PROCESSABLE_DOCUMENT_STATUSES:
            raise ValueError(f"unsupported document status: {record.status}")

        prepared_record = self._mark_next_stage_started(record)
        self._schedule_ingestion(prepared_record)
        return prepared_record.to_summary()

    def list_documents(self) -> list[DocumentSummary]:
        """查询文档列表。"""
        self.repository.init_schema()
        return [record.to_summary() for record in self.repository.list_documents()]

    def resume_processing_documents(self) -> None:
        """标记因进程重启或旧请求中断而停留在运行阶段的文档。"""
        self.repository.init_schema()
        for record in self.repository.list_interrupted_documents():
            self.repository.mark_failed(record.id, "处理被中断，请重新触发")

    def search_documents(self, query: str, top_k: int | None = None) -> DocumentSearchResponse:
        """检索个人文档。"""
        search_query = query.strip()
        if not search_query:
            raise ValueError("query cannot be empty")

        limit = top_k or self.config.retrieval_top_k
        if limit <= 0:
            limit = self.config.retrieval_top_k
        hits = self.vector_store.search(search_query, limit)
        return DocumentSearchResponse(
            query=search_query,
            results=[
                DocumentSearchResult(
                    document_id=hit.document_id,
                    filename=hit.filename,
                    chunk_index=hit.chunk_index,
                    content=hit.content,
                    score=hit.score,
                )
                for hit in hits
            ],
        )

    def delete_document(self, document_id: str) -> DocumentDeleteResponse:
        """删除文档、原文件、解析文本和向量。"""
        self.repository.init_schema()
        record = self.repository.get_by_id(document_id)
        if record is None:
            raise ValueError("document not found")

        self.vector_store.delete_document(record.id, record.chunk_count)
        delete_file_if_exists(record.original_path)
        delete_file_if_exists(record.parsed_text_path)
        self.repository.delete(record.id)
        return DocumentDeleteResponse(id=record.id, deleted=True)

    def _ingest_record(self, record: DocumentRecord) -> DocumentRecord:
        """按文档当前状态续跑解析、切分和向量化流程。"""
        current = record
        if current.status == DOCUMENT_STATUS_UPLOADED:
            current = self.repository.mark_stage_started(current.id, DOCUMENT_STATUS_PARSING)
        if current.status == DOCUMENT_STATUS_PARSING:
            current = self._parse_record(current)
        if current.status == DOCUMENT_STATUS_PARSED:
            current = self.repository.mark_stage_started(current.id, DOCUMENT_STATUS_CHUNKING)
        if current.status == DOCUMENT_STATUS_CHUNKING:
            current = self._chunk_record(current)
        if current.status == DOCUMENT_STATUS_CHUNKED:
            current = self.repository.mark_stage_started(current.id, DOCUMENT_STATUS_VECTORIZING)
        if current.status == DOCUMENT_STATUS_VECTORIZING:
            current = self._vectorize_record(current)
        return current

    def _parse_record(self, record: DocumentRecord) -> DocumentRecord:
        """解析原始文件并落盘完整纯文本。"""
        original_path = Path(record.original_path)
        if not original_path.exists():
            raise DocumentServiceError("原始文件不存在，无法继续处理")

        text = parse_document(original_path, record.filename)
        parsed_text_path = self.config.parsed_text_dir / f"{record.id}.txt"
        parsed_text_path.parent.mkdir(parents=True, exist_ok=True)
        parsed_text_path.write_text(text, encoding="utf-8")
        return self.repository.mark_parsed(record.id, str(parsed_text_path))

    def _chunk_record(self, record: DocumentRecord) -> DocumentRecord:
        """切分解析后的完整文本并记录 chunk 数量。"""
        chunks = self._load_chunks(record)
        if not chunks:
            raise ValueError("文档切分后没有可用片段")
        return self.repository.mark_chunked(record.id, len(chunks))

    def _vectorize_record(self, record: DocumentRecord) -> DocumentRecord:
        """把 chunks 写入 pgvector。"""
        chunks = self._load_chunks(record)
        if not chunks:
            raise ValueError("文档切分后没有可用片段")

        self.vector_store.delete_document(record.id, record.chunk_count)
        self.vector_store.add_chunks(record.id, record.filename, record.md5, chunks)
        return self.repository.mark_ready(record.id, len(chunks))

    def _load_chunks(self, record: DocumentRecord):
        """从解析文本文件重新切分，便于失败后按状态续跑。"""
        if not record.parsed_text_path:
            raise DocumentServiceError("解析文本不存在，无法继续处理")
        parsed_text_path = Path(record.parsed_text_path)
        if not parsed_text_path.exists():
            raise DocumentServiceError("解析文本文件不存在，无法继续处理")
        text = parsed_text_path.read_text(encoding="utf-8")
        return split_document_text(text, self.config.chunk_size, self.config.chunk_overlap)

    def _mark_next_stage_started(self, record: DocumentRecord) -> DocumentRecord:
        """根据当前进度进入下一段运行中状态。"""
        if record.status in {DOCUMENT_STATUS_UPLOADED, DOCUMENT_STATUS_PARSING}:
            return self.repository.mark_stage_started(record.id, DOCUMENT_STATUS_PARSING)
        if record.status in {DOCUMENT_STATUS_PARSED, DOCUMENT_STATUS_CHUNKING}:
            return self.repository.mark_stage_started(record.id, DOCUMENT_STATUS_CHUNKING)
        if record.status in {DOCUMENT_STATUS_CHUNKED, DOCUMENT_STATUS_VECTORIZING}:
            return self.repository.mark_stage_started(record.id, DOCUMENT_STATUS_VECTORIZING)
        return record

    def _schedule_ingestion(self, record: DocumentRecord) -> None:
        """把耗时摄取任务放到后台线程执行，避免阻塞 HTTP 事件循环。"""
        if record.id in self._active_ingestions:
            return
        self._active_ingestions.add(record.id)
        task = asyncio.create_task(asyncio.to_thread(self._ingest_record_safely, record))
        task.add_done_callback(lambda _: self._active_ingestions.discard(record.id))

    def _ingest_record_safely(self, record: DocumentRecord) -> None:
        """执行后台摄取并把失败原因写回元数据表。"""
        try:
            self._ingest_record(record)
        except (DocumentParseError, ValueError, VectorStoreError, DocumentServiceError) as exc:
            self.repository.mark_failed(record.id, str(exc))
            log.warning("个人文档摄取失败, document_id=%s, filename=%s, error=%s", record.id, record.filename, exc)
        except Exception as exc:
            error_message = f"文档摄取失败: {exc}"
            self.repository.mark_failed(record.id, error_message)
            log.exception("个人文档摄取异常, document_id=%s, filename=%s", record.id, record.filename)

    def _save_original_file(self, document_id: str, filename: str, content: bytes) -> Path:
        """保存原始上传文件。"""
        self.config.upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        path = self.config.upload_dir / f"{document_id}{suffix}"
        path.write_bytes(content)
        return path


def row_to_record(row: dict[str, Any] | None) -> DocumentRecord:
    """把数据库行转换为 DocumentRecord。"""
    if row is None:
        raise DocumentServiceError("数据库没有返回文档记录")
    return DocumentRecord(
        id=str(row["id"]),
        filename=str(row["filename"]),
        content_type=str(row["content_type"]),
        size_bytes=int(row["size_bytes"]),
        md5=str(row["md5"]),
        original_path=str(row["original_path"]),
        parsed_text_path=str(row["parsed_text_path"]) if row.get("parsed_text_path") else None,
        status=str(row["status"]),
        chunk_count=int(row["chunk_count"]),
        is_failed=bool(row["is_failed"]),
        error_message=str(row["error_message"]) if row.get("error_message") else None,
        failed_at=row["failed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def calculate_md5(content: bytes) -> str:
    """计算文件 MD5，用于本地重复文件识别。"""
    return hashlib.md5(content).hexdigest()


def upload_response(record: DocumentRecord, duplicate: bool) -> DocumentUploadResponse:
    """构造上传响应。"""
    return DocumentUploadResponse(**record.to_summary().model_dump(), duplicate=duplicate)


def delete_file_if_exists(path: str | None) -> None:
    """删除本地文件，文件不存在时忽略。"""
    if not path:
        return
    file_path = Path(path)
    if file_path.exists():
        file_path.unlink()


rag_document_service = DocumentService()
