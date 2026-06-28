"""BGE-M3 embedding 封装。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.rag_config import RagConfig, load_rag_config


class EmbeddingServiceError(RuntimeError):
    """Embedding 初始化或调用失败。"""


class BgeM3EmbeddingService:
    """本地 BGE-M3 dense embedding 服务。

    模型在首次使用时懒加载，避免普通健康检查和聊天接口启动时下载或加载模型。
    """

    def __init__(self, config: RagConfig | None = None) -> None:
        self.config = config or load_rag_config()
        self._embeddings: Any | None = None

    @property
    def langchain_embeddings(self) -> Any:
        """返回 LangChain Embeddings 实例。"""
        if self._embeddings is None:
            self._embeddings = self._build_embeddings()
        return self._embeddings

    def embed_query(self, query: str) -> list[float]:
        """向量化查询文本。"""
        return self.langchain_embeddings.embed_query(query)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化文档片段。"""
        return self.langchain_embeddings.embed_documents(texts)

    def _build_embeddings(self) -> Any:
        """创建 HuggingFaceEmbeddings。"""
        validate_torch_version()
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            raise EmbeddingServiceError("缺少 langchain-huggingface 依赖，无法加载 BGE-M3") from exc

        try:
            return HuggingFaceEmbeddings(
                model_name=self.config.embedding_model,
                model_kwargs={"device": self.config.embedding_device},
                encode_kwargs={"normalize_embeddings": True},
            )
        except Exception as exc:
            raise EmbeddingServiceError(f"BGE-M3 embedding 初始化失败: {exc}") from exc


def validate_torch_version() -> None:
    """确认 torch 版本满足 Transformers 安全加载要求。"""
    try:
        torch_version = version("torch")
    except PackageNotFoundError as exc:
        raise EmbeddingServiceError("缺少 torch 依赖，无法加载 BGE-M3") from exc

    if parse_major_minor(torch_version) < (2, 6):
        raise EmbeddingServiceError(
            f"当前 torch 版本为 {torch_version}，BGE-M3 需要 torch>=2.6；请重新同步 services/python-api 依赖",
        )


def parse_major_minor(raw_version: str) -> tuple[int, int]:
    """解析形如 2.6.0 或 2.6.0+cpu 的主次版本。"""
    version_part = raw_version.split("+", 1)[0]
    parts = version_part.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError as exc:
        raise EmbeddingServiceError(f"无法识别 torch 版本: {raw_version}") from exc
    return major, minor
