"""Python API 的请求和响应模型。

所有对外接口都通过 Pydantic 模型声明数据结构，便于 FastAPI 自动生成
OpenAPI 文档，也让前端联调时能看到稳定的字段契约。
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应体。

    @param code: 业务响应码，0 表示成功。
    @param message: 响应说明。
    @param data: 真实业务数据。
    """

    code: int
    message: str
    data: T


class SiteInfo(BaseModel):
    """站点服务信息。

    前端首页服务状态卡片会读取这些字段展示 Python API 状态。
    """

    service: str
    language: str
    status: str
    description: str


class HealthStatus(BaseModel):
    """健康检查结果。"""

    service: str
    status: str


class ChatRequest(BaseModel):
    """AI 对话请求。

    @param message: 用户输入内容。
    @param session_id: 后端会话 ID；为空表示创建新会话。
    @param web_search_enabled: 是否允许本轮对话使用联网搜索工具。
    @param rag_enabled: 是否允许本轮对话使用个人文档 RAG 工具。
    """

    message: str
    session_id: str | None = None
    web_search_enabled: bool = True
    rag_enabled: bool = True


class ChatMessage(BaseModel):
    """会话历史中的单条消息。

    @param role: 消息角色，当前使用 `user` 或 `assistant`。
    @param content: 正式消息内容。
    @param thinking: assistant 消息的思考过程，模型未返回时为空。
    """

    role: str
    content: str
    thinking: str | None = None


class ToolCallRecord(BaseModel):
    """AI 对话中的工具调用记录。

    @param name: 工具名称，例如 `web_search`。
    @param status: 调用状态，当前使用 `success` 或 `error`。
    @param input: 工具入参。
    @param output: 工具出参，失败时为空。
    @param error: 失败原因，成功时为空。
    """

    name: str
    status: str
    input: dict[str, Any]
    output: Any | None = None
    error: str | None = None


class ChatResponse(BaseModel):
    """AI 对话响应。

    @param session_id: 后端会话 ID。
    @param answer: 当前轮 assistant 的正式回复。
    @param thinking: 当前轮 assistant 的思考过程。
    @param tools: 当前轮对话触发的工具调用记录。
    @param history: 当前会话保留的历史消息。
    """

    session_id: str
    answer: str
    thinking: str | None = None
    tools: list[ToolCallRecord] | None = None
    history: list[ChatMessage]


class DocumentSummary(BaseModel):
    """个人文档摘要。

    @param id: 文档 ID。
    @param filename: 原始文件名。
    @param content_type: 上传文件 Content-Type。
    @param size_bytes: 文件大小。
    @param md5: 文件 MD5，用于本地判重。
    @param original_path: 原始上传文件本地路径。
    @param parsed_text_path: 解析后的完整纯文本本地路径。
    @param status: 摄取进度，当前使用 `uploaded`、`parsing`、`parsed`、`chunking`、`chunked`、`vectorizing`、`ready`。
    @param chunk_count: 已写入向量库的 chunk 数量。
    @param is_failed: 当前进度是否失败；失败时 status 保留在失败发生的阶段。
    @param error_message: 摄取失败原因。
    @param failed_at: 最近一次失败时间。
    @param created_at: 创建时间。
    @param updated_at: 更新时间。
    """

    id: str
    filename: str
    content_type: str
    size_bytes: int
    md5: str
    original_path: str
    parsed_text_path: str | None = None
    status: str
    chunk_count: int
    is_failed: bool = False
    error_message: str | None = None
    failed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(DocumentSummary):
    """个人文档上传响应。

    @param duplicate: 是否命中 MD5 判重。
    """

    duplicate: bool = False


class DocumentSearchRequest(BaseModel):
    """个人文档检索请求。

    @param query: 检索问题，不能为空。
    @param top_k: 返回结果数量，不传时使用后端配置。
    """

    query: str
    top_k: int | None = None


class DocumentSearchResult(BaseModel):
    """个人文档检索结果。"""

    document_id: str
    filename: str
    chunk_index: int
    content: str
    score: float


class DocumentSearchResponse(BaseModel):
    """个人文档检索响应。"""

    query: str
    results: list[DocumentSearchResult]


class DocumentDeleteResponse(BaseModel):
    """个人文档删除响应。"""

    id: str
    deleted: bool
