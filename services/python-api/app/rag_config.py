"""个人文档 RAG 配置。

配置优先级为当前进程环境变量、服务目录本地 env 文件、`~/.claude/settings.json` 的 env 字段。
路径类配置支持相对路径，默认相对 `services/python-api` 目录解析。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PGVECTOR_CONNECTION = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"
DEFAULT_PGVECTOR_COLLECTION = "personal_documents_bge_m3"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_BGE_M3_SAFETENSORS_REVISION = "refs/pr/130"
DEFAULT_EMBEDDING_DEVICE = "cpu"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_RETRIEVAL_TOP_K = 5
DEFAULT_UPLOAD_DIR = "data/uploads"
DEFAULT_PARSED_TEXT_DIR = "data/parsed"


@dataclass(frozen=True)
class RagConfig:
    """个人文档 RAG 运行配置。"""

    pgvector_connection: str
    pgvector_collection: str
    embedding_model: str
    embedding_revision: str | None
    embedding_device: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    upload_dir: Path
    parsed_text_dir: Path


def load_rag_config() -> RagConfig:
    """读取 RAG 配置。"""
    settings_env = load_config_from_settings()
    local_env = load_local_env_config()
    chunk_size = parse_positive_int("RAG_CHUNK_SIZE", local_env, settings_env, DEFAULT_CHUNK_SIZE)
    chunk_overlap = parse_positive_int("RAG_CHUNK_OVERLAP", local_env, settings_env, DEFAULT_CHUNK_OVERLAP)
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)

    embedding_model = read_config("RAG_EMBEDDING_MODEL", local_env, settings_env, DEFAULT_EMBEDDING_MODEL)
    embedding_revision = read_optional_config("RAG_EMBEDDING_REVISION", local_env, settings_env)
    if embedding_revision is None and embedding_model == DEFAULT_EMBEDDING_MODEL:
        embedding_revision = DEFAULT_BGE_M3_SAFETENSORS_REVISION

    return RagConfig(
        pgvector_connection=read_config(
            "RAG_PGVECTOR_CONNECTION",
            local_env,
            settings_env,
            DEFAULT_PGVECTOR_CONNECTION,
        ),
        pgvector_collection=read_config(
            "RAG_PGVECTOR_COLLECTION",
            local_env,
            settings_env,
            DEFAULT_PGVECTOR_COLLECTION,
        ),
        embedding_model=embedding_model,
        embedding_revision=embedding_revision,
        embedding_device=read_config("RAG_EMBEDDING_DEVICE", local_env, settings_env, DEFAULT_EMBEDDING_DEVICE),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        retrieval_top_k=parse_positive_int("RAG_RETRIEVAL_TOP_K", local_env, settings_env, DEFAULT_RETRIEVAL_TOP_K),
        upload_dir=resolve_data_path(read_config("RAG_UPLOAD_DIR", local_env, settings_env, DEFAULT_UPLOAD_DIR)),
        parsed_text_dir=resolve_data_path(
            read_config("RAG_PARSED_TEXT_DIR", local_env, settings_env, DEFAULT_PARSED_TEXT_DIR),
        ),
    )


def read_config(name: str, local_env: dict[str, str], settings_env: dict[str, str], default: str) -> str:
    """按环境变量优先级读取字符串配置。"""
    return os.environ.get(name) or local_env.get(name) or settings_env.get(name) or default


def read_optional_config(name: str, local_env: dict[str, str], settings_env: dict[str, str]) -> str | None:
    """按环境变量优先级读取可选字符串配置。"""
    value = os.environ.get(name) or local_env.get(name) or settings_env.get(name)
    return value or None


def parse_positive_int(name: str, local_env: dict[str, str], settings_env: dict[str, str], default: int) -> int:
    """读取正整数配置，非法值回退到默认值。"""
    raw_value = os.environ.get(name) or local_env.get(name) or settings_env.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def resolve_data_path(value: str) -> Path:
    """把路径配置解析为绝对路径。

    兼容两种写法：
    - `data/uploads`: 相对 `services/python-api`；
    - `services/python-api/data/uploads`: 相对仓库根目录。
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path

    python_api_root = Path(__file__).resolve().parents[1]
    repo_root = python_api_root.parents[1]
    parts = path.parts
    if len(parts) >= 2 and parts[0] == "services" and parts[1] == "python-api":
        return (repo_root / path).resolve()
    return (python_api_root / path).resolve()


def normalize_psycopg_connection(connection: str) -> str:
    """把 SQLAlchemy 风格 psycopg URL 转成 psycopg 可直接连接的 URL。"""
    if connection.startswith("postgresql+psycopg://"):
        return "postgresql://" + connection.removeprefix("postgresql+psycopg://")
    return connection


def load_local_env_config() -> dict[str, str]:
    """读取服务目录下的 `.env` 和 `.env.local`。"""
    python_api_root = Path(__file__).resolve().parents[1]
    env: dict[str, str] = {}
    for filename in [".env", ".env.local"]:
        env.update(parse_env_file(python_api_root / filename))
    return env


def parse_env_file(path: Path) -> dict[str, str]:
    """解析简单 KEY=VALUE 格式的 env 文件。"""
    if not path.exists():
        return {}

    env: dict[str, str] = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            if stripped.startswith("export "):
                stripped = stripped.removeprefix("export ").strip()
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            env[key] = value
    return env


def load_config_from_settings() -> dict[str, str]:
    """从 `~/.claude/settings.json` 的 env 字段读取配置。"""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}

    with settings_path.open(encoding="utf-8") as file:
        settings = json.load(file)
    env = settings.get("env", {})
    if not isinstance(env, dict):
        return {}
    return {str(key): str(value) for key, value in env.items()}
