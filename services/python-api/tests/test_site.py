import asyncio
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

import app.main as main_module
from app.ai_chat import build_system_prompt, extract_text_content, extract_thinking_content, format_current_time
from app.document_chunker import split_document_text
from app.document_parser import parse_document
from app.document_service import DocumentRecord, DocumentService, calculate_md5
from app.main import app
from app.rag_config import RagConfig
from app.schemas import (
    ChatMessage,
    ChatResponse,
    DocumentDeleteResponse,
    DocumentSearchResponse,
    DocumentSearchResult,
    DocumentSummary,
    DocumentUploadResponse,
)
from app.web_search import WebSearchResponse, WebSearchResult, build_web_search_context

client = TestClient(app)


class StubChatService:
    """测试替身。

    用固定响应替代真实模型调用，避免单测依赖 token、网络和模型服务。
    """

    def __init__(self) -> None:
        self.chat_calls = []
        self.stream_calls = []

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        web_search_enabled: bool = True,
        rag_enabled: bool = True,
    ) -> ChatResponse:
        """返回一轮固定非流式响应。"""
        self.chat_calls.append(
            {
                "message": message,
                "session_id": session_id,
                "web_search_enabled": web_search_enabled,
                "rag_enabled": rag_enabled,
            },
        )
        current_session_id = session_id or "test-session"
        return ChatResponse(
            session_id=current_session_id,
            answer=f"Echo: {message}",
            history=[
                ChatMessage(role="user", content=message),
                ChatMessage(role="assistant", content=f"Echo: {message}"),
            ],
        )

    async def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        web_search_enabled: bool = True,
        rag_enabled: bool = True,
    ):
        """按真实 SSE 事件顺序返回固定流式响应。"""
        self.stream_calls.append(
            {
                "message": message,
                "session_id": session_id,
                "web_search_enabled": web_search_enabled,
                "rag_enabled": rag_enabled,
            },
        )
        current_session_id = session_id or "test-session"
        yield {"event": "session", "session_id": current_session_id}
        yield {"event": "on_tool_start", "name": "web_search", "data": {"input": {"query": message}}}
        yield {
            "event": "on_tool_end",
            "name": "web_search",
            "data": {
                "output": {
                    "status": "success",
                    "provider": "tavily",
                    "query": message,
                    "results": [
                        {
                            "title": "Shane's Site",
                            "url": "https://example.com",
                            "snippet": "Personal site search result.",
                        },
                    ],
                },
            },
        }
        yield {"event": "on_chat_model_stream", "name": "model", "data": {"thinking": "先判断用户意图。", "text": ""}}
        yield {"event": "on_chat_model_stream", "name": "model", "data": {"text": "Echo: "}}
        yield {"event": "on_chat_model_stream", "name": "model", "data": {"text": message}}
        yield {
            "event": "agent_done",
            "session_id": current_session_id,
            "answer": f"Echo: {message}",
            "thinking": "先判断用户意图。",
            "tools": [
                {
                    "name": "web_search",
                    "status": "success",
                    "input": {"query": message},
                    "output": {
                        "provider": "tavily",
                        "query": message,
                        "results": [
                            {
                                "title": "Shane's Site",
                                "url": "https://example.com",
                                "snippet": "Personal site search result.",
                            },
                        ],
                    },
                },
            ],
            "history": [
                {"role": "user", "content": message},
                {"role": "assistant", "content": f"Echo: {message}", "thinking": "先判断用户意图。"},
            ],
        }


class StubDocumentService:
    """个人文档服务测试替身。"""

    def __init__(self) -> None:
        self.upload_calls = []
        self.process_calls = []
        self.search_calls = []
        self.deleted_ids = []
        self.summary = DocumentSummary(
            id="doc-1",
            filename="notes.md",
            content_type="text/markdown",
            size_bytes=12,
            md5="ebd0767a0e5594c08c1e2b2f752e8871",
            original_path="/tmp/uploads/doc-1.md",
            parsed_text_path="/tmp/parsed/doc-1.txt",
            status="ready",
            chunk_count=1,
            created_at="2026-06-26T00:00:00+08:00",
            updated_at="2026-06-26T00:00:00+08:00",
        )

    async def upload_document(self, file) -> DocumentUploadResponse:
        """记录上传文件并返回固定响应。"""
        self.upload_calls.append(file.filename)
        return DocumentUploadResponse(**self.summary.model_dump(), duplicate=False)

    def list_documents(self) -> list[DocumentSummary]:
        """返回固定文档列表。"""
        return [self.summary]

    def process_document(self, document_id: str) -> DocumentSummary:
        """记录处理 ID 并返回固定文档状态。"""
        self.process_calls.append(document_id)
        return self.summary

    def search_documents(self, query: str, top_k: int | None = None) -> DocumentSearchResponse:
        """返回固定检索结果。"""
        self.search_calls.append({"query": query, "top_k": top_k})
        return DocumentSearchResponse(
            query=query,
            results=[
                DocumentSearchResult(
                    document_id="doc-1",
                    filename="notes.md",
                    chunk_index=0,
                    content="Shane 的个人笔记",
                    score=0.12,
                ),
            ],
        )

    def delete_document(self, document_id: str) -> DocumentDeleteResponse:
        """记录删除 ID。"""
        self.deleted_ids.append(document_id)
        return DocumentDeleteResponse(id=document_id, deleted=True)


class FakeDocumentRepository:
    """内存文档元数据仓储。"""

    def __init__(self, records: list[DocumentRecord] | None = None) -> None:
        self.records = {record.id: record for record in records or []}
        self.created_count = 0

    def init_schema(self) -> None:
        """测试替身无需初始化结构。"""

    def get_by_md5(self, md5: str) -> DocumentRecord | None:
        """按 MD5 查询内存记录。"""
        return next((record for record in self.records.values() if record.md5 == md5), None)

    def get_by_id(self, document_id: str) -> DocumentRecord | None:
        """按 ID 查询内存记录。"""
        return self.records.get(document_id)

    def list_documents(self) -> list[DocumentRecord]:
        """返回全部内存记录。"""
        return list(self.records.values())

    def list_interrupted_documents(self) -> list[DocumentRecord]:
        """测试中不需要恢复中断任务。"""
        return []

    def create_uploaded(
        self,
        document_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        md5: str,
        original_path: str,
    ) -> DocumentRecord:
        """创建 uploaded 状态记录。"""
        now = datetime(2026, 6, 26, 0, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        record = DocumentRecord(
            id=document_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            md5=md5,
            original_path=original_path,
            parsed_text_path=None,
            status="uploaded",
            chunk_count=0,
            is_failed=False,
            error_message=None,
            failed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.records[document_id] = record
        self.created_count += 1
        return record

    def mark_stage_started(self, document_id: str, status: str) -> DocumentRecord:
        """更新运行中阶段。"""
        return self._update(
            document_id,
            status=status,
            is_failed=False,
            error_message=None,
            failed_at=None,
        )

    def mark_parsed(self, document_id: str, parsed_text_path: str) -> DocumentRecord:
        """更新解析完成状态。"""
        return self._update(document_id, status="parsed", parsed_text_path=parsed_text_path, is_failed=False)

    def mark_chunked(self, document_id: str, chunk_count: int) -> DocumentRecord:
        """更新切分完成状态。"""
        return self._update(document_id, status="chunked", chunk_count=chunk_count, is_failed=False)

    def mark_ready(self, document_id: str, chunk_count: int) -> DocumentRecord:
        """更新向量化完成状态。"""
        return self._update(document_id, status="ready", chunk_count=chunk_count, is_failed=False)

    def mark_failed(self, document_id: str, error_message: str) -> DocumentRecord:
        """标记失败但保留当前 status。"""
        failed_at = datetime(2026, 6, 26, 0, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return self._update(
            document_id,
            is_failed=True,
            error_message=error_message,
            failed_at=failed_at,
        )

    def delete(self, document_id: str) -> None:
        """删除内存记录。"""
        self.records.pop(document_id, None)

    def _update(self, document_id: str, **changes) -> DocumentRecord:
        record = replace(self.records[document_id], **changes)
        self.records[document_id] = record
        return record


class FakeVectorStore:
    """内存向量库替身。"""

    def __init__(self) -> None:
        self.added_chunks = []
        self.deleted_documents = []

    def add_chunks(self, document_id: str, filename: str, md5: str, chunks) -> None:
        """记录写入的 chunks。"""
        self.added_chunks.append(
            {
                "document_id": document_id,
                "filename": filename,
                "md5": md5,
                "chunks": chunks,
            },
        )

    def delete_document(self, document_id: str, chunk_count: int) -> None:
        """记录删除向量请求。"""
        self.deleted_documents.append({"document_id": document_id, "chunk_count": chunk_count})

    def search(self, query: str, top_k: int):
        """服务层检索测试未使用。"""
        return []


def build_document_service(
    tmp_path: Path,
    repository: FakeDocumentRepository,
    vector_store: FakeVectorStore | None = None,
) -> DocumentService:
    """构造不依赖真实 pgvector 的文档服务。"""
    config = RagConfig(
        pgvector_connection="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres",
        pgvector_collection="test_documents",
        embedding_model="BAAI/bge-m3",
        embedding_revision="refs/pr/130",
        embedding_device="cpu",
        chunk_size=12,
        chunk_overlap=2,
        retrieval_top_k=3,
        upload_dir=tmp_path / "uploads",
        parsed_text_dir=tmp_path / "parsed",
    )
    return DocumentService(config=config, repository=repository, vector_store=vector_store or FakeVectorStore())


def build_document_record(
    document_id: str,
    md5: str = "ebd0767a0e5594c08c1e2b2f752e8871",
    original_path: str = "/tmp/uploads/doc-1.md",
    parsed_text_path: str | None = None,
    status: str = "uploaded",
    chunk_count: int = 0,
    is_failed: bool = False,
) -> DocumentRecord:
    """构造固定时间的文档元数据记录。"""
    now = datetime(2026, 6, 26, 0, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    return DocumentRecord(
        id=document_id,
        filename="notes.md",
        content_type="text/markdown",
        size_bytes=12,
        md5=md5,
        original_path=original_path,
        parsed_text_path=parsed_text_path,
        status=status,
        chunk_count=chunk_count,
        is_failed=is_failed,
        error_message=None,
        failed_at=None,
        created_at=now,
        updated_at=now,
    )


def build_upload_file(filename: str, content: bytes) -> UploadFile:
    """构造内存上传文件。"""
    return UploadFile(file=BytesIO(content), filename=filename)


def test_get_site_info_returns_unified_response():
    response = client.get("/api/site")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "service": "python-api",
            "language": "Python",
            "status": "UP",
            "description": "FastAPI service for Shane's personal site",
        },
    }


def test_get_health_returns_unified_response():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "service": "python-api",
            "status": "UP",
        },
    }


def test_openapi_docs_are_available():
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_chat_with_ai_returns_session_history(monkeypatch):
    stub_service = StubChatService()
    monkeypatch.setattr(main_module, "chat_service", stub_service)

    response = client.post(
        "/api/chat",
        json={
            "session_id": "abc123",
            "message": "你好",
            "web_search_enabled": False,
            "rag_enabled": False,
        },
    )

    assert response.status_code == 200
    assert stub_service.chat_calls == [
        {
            "message": "你好",
            "session_id": "abc123",
            "web_search_enabled": False,
            "rag_enabled": False,
        },
    ]
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "session_id": "abc123",
            "answer": "Echo: 你好",
            "history": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "Echo: 你好"},
            ],
        },
    }


def test_extract_text_content_uses_only_text_parts():
    content = [
        {"type": "text", "text": "你好"},
        {"type": "thinking", "thinking": "先判断用户问候。"},
        {"type": "tool_use", "name": "search", "input": {"q": "ignore"}},
        {"type": "text", "text": "，Shane"},
    ]

    assert extract_text_content(content) == "你好，Shane"


def test_extract_thinking_content_uses_reasoning_parts():
    content = [
        {"type": "reasoning", "reasoning_content": "先识别问题类型。"},
        {"type": "text", "text": "正式回复"},
    ]

    assert extract_thinking_content(content) == "先识别问题类型。"


def test_build_system_prompt_respects_web_search_switch():
    assert "web_search" in build_system_prompt(True)
    assert "未启用联网搜索" in build_system_prompt(False)


def test_build_system_prompt_respects_rag_switch():
    assert "personal_knowledge_search" in build_system_prompt(True, True)
    assert "未启用个人文档 RAG" in build_system_prompt(True, False)


def test_build_system_prompt_includes_current_time():
    current_time = datetime(2026, 6, 25, 15, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    prompt = build_system_prompt(True, True, current_time)

    assert "当前时间：2026-06-25 15:30:00 CST (Asia/Shanghai)" in prompt
    assert "相对时间" in prompt


def test_format_current_time_includes_timezone():
    current_time = datetime(2026, 6, 25, 15, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert format_current_time(current_time) == "2026-06-25 15:30:00 CST (Asia/Shanghai)"


def test_build_web_search_context_formats_results():
    response = WebSearchResponse(
        provider="tavily",
        query="Shane",
        results=[
            WebSearchResult(
                title="Shane's Site",
                url="https://example.com",
                snippet="Personal site search result.",
            ),
        ],
    )

    context = build_web_search_context(response)

    assert "provider=tavily" in context
    assert "https://example.com" in context


def test_parse_markdown_document_and_split_text(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# 标题\n\n这是第一段。\n\n这是第二段。", encoding="utf-8")

    text = parse_document(path)
    chunks = split_document_text(text, chunk_size=12, chunk_overlap=2)

    assert "第一段" in text
    assert chunks
    assert chunks[0].chunk_index == 0


def test_calculate_md5_returns_stable_hash():
    assert calculate_md5(b"hello") == "5d41402abc4b2a76b9719d911017c592"


def test_upload_duplicate_document_returns_existing_without_saving_file(tmp_path):
    content = b"# hello"
    existing = build_document_record(
        document_id="doc-1",
        md5=calculate_md5(content),
        original_path=str(tmp_path / "existing.md"),
        status="ready",
    )
    repository = FakeDocumentRepository([existing])
    service = build_document_service(tmp_path, repository)

    result = asyncio.run(service.upload_document(build_upload_file("copy.md", content)))

    assert result.duplicate is True
    assert result.id == "doc-1"
    assert repository.created_count == 0
    assert not list((tmp_path / "uploads").glob("*"))


def test_upload_new_document_creates_uploaded_metadata(tmp_path):
    repository = FakeDocumentRepository()
    service = build_document_service(tmp_path, repository)

    result = asyncio.run(service.upload_document(build_upload_file("notes.md", b"# hello")))

    assert result.duplicate is False
    assert result.status == "uploaded"
    assert result.is_failed is False
    assert repository.created_count == 1
    assert Path(result.original_path).exists()


def test_process_failure_keeps_stage_status_for_retry(tmp_path):
    record = build_document_record(
        document_id="doc-1",
        original_path=str(tmp_path / "missing.md"),
        status="uploaded",
    )
    repository = FakeDocumentRepository([record])
    service = build_document_service(tmp_path, repository)
    service._schedule_ingestion = lambda prepared: service._ingest_record_safely(prepared)

    result = service.process_document("doc-1")
    failed_record = repository.get_by_id("doc-1")

    assert result.status == "parsing"
    assert failed_record.status == "parsing"
    assert failed_record.is_failed is True
    assert failed_record.error_message == "原始文件不存在，无法继续处理"


def test_chunk_failure_keeps_chunking_status_for_retry(tmp_path):
    parsed_path = tmp_path / "parsed" / "doc-1.txt"
    parsed_path.parent.mkdir(parents=True)
    parsed_path.write_text("   ", encoding="utf-8")
    record = build_document_record(
        document_id="doc-1",
        parsed_text_path=str(parsed_path),
        status="parsed",
    )
    repository = FakeDocumentRepository([record])
    service = build_document_service(tmp_path, repository)
    service._schedule_ingestion = lambda prepared: service._ingest_record_safely(prepared)

    result = service.process_document("doc-1")
    failed_record = repository.get_by_id("doc-1")

    assert result.status == "chunking"
    assert failed_record.status == "chunking"
    assert failed_record.is_failed is True
    assert failed_record.error_message == "text cannot be empty"


def test_process_chunked_document_resumes_vectorizing(tmp_path):
    parsed_path = tmp_path / "parsed" / "doc-1.txt"
    parsed_path.parent.mkdir(parents=True)
    parsed_path.write_text("第一段内容。\n\n第二段内容。", encoding="utf-8")
    record = build_document_record(
        document_id="doc-1",
        parsed_text_path=str(parsed_path),
        status="chunked",
        chunk_count=2,
    )
    repository = FakeDocumentRepository([record])
    vector_store = FakeVectorStore()
    service = build_document_service(tmp_path, repository, vector_store)
    service._schedule_ingestion = lambda prepared: service._ingest_record_safely(prepared)

    result = service.process_document("doc-1")
    ready_record = repository.get_by_id("doc-1")

    assert result.status == "vectorizing"
    assert ready_record.status == "ready"
    assert ready_record.is_failed is False
    assert vector_store.deleted_documents == [{"document_id": "doc-1", "chunk_count": 2}]
    assert vector_store.added_chunks[0]["document_id"] == "doc-1"


def test_document_upload_list_search_and_delete_routes(monkeypatch):
    stub_service = StubDocumentService()
    monkeypatch.setattr(main_module, "rag_document_service", stub_service)

    upload_response = client.post(
        "/api/documents/upload",
        files={"file": ("notes.md", b"# hello", "text/markdown")},
    )
    list_response = client.get("/api/documents")
    process_response = client.post("/api/documents/doc-1/process")
    search_response = client.post("/api/documents/search", json={"query": "个人笔记", "top_k": 3})
    delete_response = client.delete("/api/documents/doc-1")

    assert upload_response.status_code == 200
    assert upload_response.json()["data"]["filename"] == "notes.md"
    assert upload_response.json()["data"]["duplicate"] is False
    assert list_response.json()["data"][0]["md5"] == "ebd0767a0e5594c08c1e2b2f752e8871"
    assert process_response.json()["data"]["status"] == "ready"
    assert search_response.json()["data"]["results"][0]["content"] == "Shane 的个人笔记"
    assert delete_response.json()["data"] == {"id": "doc-1", "deleted": True}
    assert stub_service.upload_calls == ["notes.md"]
    assert stub_service.process_calls == ["doc-1"]
    assert stub_service.search_calls == [{"query": "个人笔记", "top_k": 3}]
    assert stub_service.deleted_ids == ["doc-1"]


def test_stream_chat_with_ai_returns_sse_events(monkeypatch):
    stub_service = StubChatService()
    monkeypatch.setattr(main_module, "chat_service", stub_service)

    response = client.post(
        "/api/chat/stream",
        json={
            "session_id": "abc123",
            "message": "你好",
            "web_search_enabled": False,
            "rag_enabled": False,
        },
    )

    assert response.status_code == 200
    assert stub_service.stream_calls == [
        {
            "message": "你好",
            "session_id": "abc123",
            "web_search_enabled": False,
            "rag_enabled": False,
        },
    ]
    assert "text/event-stream" in response.headers["content-type"]
    assert 'event: session\ndata: {"session_id": "abc123"}' in response.text
    assert 'event: on_tool_start\ndata: {"name": "web_search", "data": {"input": {"query": "你好"}}}' in response.text
    assert 'event: on_tool_end\ndata: {"name": "web_search"' in response.text
    assert 'event: on_chat_model_stream\ndata: {"name": "model", "data": {"thinking": "先判断用户意图。", "text": ""}}' in response.text
    assert 'event: on_chat_model_stream\ndata: {"name": "model", "data": {"text": "Echo: "}}' in response.text
    assert '"tools": [{"name": "web_search", "status": "success"' in response.text
    assert '"thinking": "先判断用户意图。"' in response.text
    assert 'event: agent_done\ndata: {"session_id": "abc123", "answer": "Echo: 你好"' in response.text
