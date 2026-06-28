"""pgvector 向量存储封装。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.document_chunker import DocumentChunk
from app.embedding_service import BgeM3EmbeddingService
from app.rag_config import RagConfig, load_rag_config


class VectorStoreError(RuntimeError):
    """向量库调用失败。"""


@dataclass(frozen=True)
class RagSearchHit:
    """个人文档检索命中结果。"""

    document_id: str
    filename: str
    chunk_index: int
    content: str
    score: float


def build_chunk_id(document_id: str, chunk_index: int) -> str:
    """生成稳定的 chunk 向量 ID。"""
    return f"{document_id}:{chunk_index}"


class PgVectorDocumentStore:
    """基于 LangChain PGVector 的个人文档向量库。"""

    def __init__(self, config: RagConfig | None = None, embeddings: Any | None = None) -> None:
        self.config = config or load_rag_config()
        self._embeddings = embeddings
        self._store: Any | None = None

    @property
    def store(self) -> Any:
        """返回懒加载的 PGVector store。"""
        if self._store is None:
            self._store = self._build_store()
        return self._store

    def add_chunks(self, document_id: str, filename: str, md5: str, chunks: list[DocumentChunk]) -> None:
        """写入文档 chunks。"""
        if not chunks:
            raise VectorStoreError("没有可写入向量库的文档片段")

        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise VectorStoreError("缺少 langchain-core 依赖，无法构造文档片段") from exc

        documents = [
            Document(
                page_content=chunk.content,
                metadata={
                    "document_id": document_id,
                    "filename": filename,
                    "chunk_index": chunk.chunk_index,
                    "source": filename,
                    "md5": md5,
                },
            )
            for chunk in chunks
        ]
        ids = [build_chunk_id(document_id, chunk.chunk_index) for chunk in chunks]
        try:
            self.store.add_documents(documents, ids=ids)
        except Exception as exc:
            raise VectorStoreError(f"写入 pgvector 失败: {exc}") from exc

    def search(self, query: str, top_k: int) -> list[RagSearchHit]:
        """执行相似度检索。"""
        try:
            results = self.store.similarity_search_with_score(query=query, k=top_k)
        except Exception as exc:
            raise VectorStoreError(f"检索 pgvector 失败: {exc}") from exc

        hits: list[RagSearchHit] = []
        for document, score in results:
            metadata = document.metadata or {}
            hits.append(
                RagSearchHit(
                    document_id=str(metadata.get("document_id", "")),
                    filename=str(metadata.get("filename", "")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    content=document.page_content,
                    score=float(score),
                ),
            )
        return hits

    def delete_document(self, document_id: str, chunk_count: int) -> None:
        """按 document_id 删除该文档所有 chunks。"""
        if chunk_count <= 0:
            return
        ids = [build_chunk_id(document_id, index) for index in range(chunk_count)]
        try:
            self.store.delete(ids=ids)
        except Exception as exc:
            raise VectorStoreError(f"删除 pgvector 文档向量失败: {exc}") from exc

    def _build_store(self) -> Any:
        """创建 PGVector 实例。"""
        try:
            from langchain_postgres import PGVector
        except ImportError as exc:
            raise VectorStoreError("缺少 langchain-postgres 依赖，无法连接 pgvector") from exc

        embeddings = self._embeddings or BgeM3EmbeddingService(self.config).langchain_embeddings
        try:
            return PGVector(
                embeddings=embeddings,
                collection_name=self.config.pgvector_collection,
                connection=self.config.pgvector_connection,
                use_jsonb=True,
            )
        except Exception as exc:
            raise VectorStoreError(f"初始化 pgvector 失败: {exc}") from exc
