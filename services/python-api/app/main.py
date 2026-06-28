"""Python API 入口。

这个模块只负责 HTTP 路由、统一响应包装和异常转换。
具体 AI 会话逻辑放在 `app.ai_chat`，避免路由层承载业务细节。
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.ai_chat import chat_service
from app.document_parser import DocumentParseError
from app.document_service import DocumentServiceError, rag_document_service
from app.schemas import (
    ApiResponse,
    ChatRequest,
    ChatResponse,
    DocumentDeleteResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentSummary,
    DocumentUploadResponse,
    HealthStatus,
    SiteInfo,
)
from app.vector_store import VectorStoreError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """服务启动时恢复未完成的个人文档摄取任务。"""
    try:
        rag_document_service.resume_processing_documents()
    except (DocumentServiceError, RuntimeError) as exc:
        log.warning("恢复个人文档摄取任务失败: %s", exc)
    yield


app = FastAPI(title="Personal Site Python API", version="0.1.0", lifespan=lifespan)


@app.get("/api/site", response_model=ApiResponse[SiteInfo])
def get_site_info() -> ApiResponse[SiteInfo]:
    """查询 Python API 服务信息。

    @return: 统一响应体，data 中包含服务名、语言、状态和说明。
    """
    return ApiResponse(
        code=0,
        message="success",
        data=SiteInfo(
            service="python-api",
            language="Python",
            status="UP",
            description="FastAPI service for Shane's personal site",
        ),
    )


@app.get("/api/health", response_model=ApiResponse[HealthStatus])
def get_health() -> ApiResponse[HealthStatus]:
    """查询 Python API 健康状态。

    @return: 统一响应体，data.status 为 `UP` 表示服务进程可用。
    """
    return ApiResponse(
        code=0,
        message="success",
        data=HealthStatus(service="python-api", status="UP"),
    )


@app.post("/api/chat", response_model=ApiResponse[ChatResponse], response_model_exclude_none=True)
async def chat_with_ai(request: ChatRequest) -> ApiResponse[ChatResponse]:
    """非流式 AI 对话接口。

    @param request: 用户消息、可选 session_id 和联网搜索开关。
    @return: 统一响应体，data 中包含 answer、thinking 和会话历史。
    """
    try:
        result = await chat_service.chat(
            request.message,
            request.session_id,
            request.web_search_enabled,
            request.rag_enabled,
        )
    except ValueError as exc:
        # 参数问题返回 400，方便前端区分用户输入错误和系统异常。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 模型配置缺失、模型调用失败等运行时问题返回 500。
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ApiResponse(code=0, message="success", data=result)


@app.post("/api/chat/stream")
async def stream_chat_with_ai(request: ChatRequest) -> StreamingResponse:
    """流式 AI 对话接口。

    使用 Server-Sent Events 推送 session、LangChain agent 事件、agent_done 和 error。
    前端通过 `on_chat_model_stream`、`on_tool_start`、`on_tool_end`、`on_tool_error`
    更新模型回复、工具调用和交互记录；`web_search_enabled=false` 时本轮不注册搜索工具，
    `rag_enabled=false` 时本轮不注册个人文档检索工具。
    """

    async def generate_events():
        """把 service 层事件转换为 SSE 字符串。"""
        try:
            async for event in chat_service.stream_chat(
                request.message,
                request.session_id,
                request.web_search_enabled,
                request.rag_enabled,
            ):
                # service 层用 event 字段标识事件名，SSE payload 不再重复携带该字段。
                event_name = event.pop("event")
                yield format_sse_event(event_name, event)
        except ValueError as exc:
            yield format_sse_event("error", {"message": str(exc)})
        except RuntimeError as exc:
            yield format_sse_event("error", {"message": str(exc)})
        except Exception as exc:
            yield format_sse_event("error", {"message": f"AI stream failed: {exc}"})

    return StreamingResponse(generate_events(), media_type="text/event-stream")


@app.post("/api/documents/upload", response_model=ApiResponse[DocumentUploadResponse], response_model_exclude_none=True)
async def upload_document(file: UploadFile = File(...)) -> ApiResponse[DocumentUploadResponse]:
    """上传个人文档并保存元数据。

    @param file: `.txt`、`.md` 或 `.pdf` 文档。
    @return: 统一响应体，data 中包含文档元数据和是否重复上传。
    """
    try:
        result = await rag_document_service.upload_document(file)
    except (ValueError, DocumentParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (DocumentServiceError, VectorStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ApiResponse(code=0, message="success", data=result)


@app.post("/api/documents/{document_id}/process", response_model=ApiResponse[DocumentSummary])
async def process_document(document_id: str) -> ApiResponse[DocumentSummary]:
    """手动触发个人文档解析、切分和向量化。"""
    try:
        result = rag_document_service.process_document(document_id)
    except ValueError as exc:
        status_code = 404 if str(exc) == "document not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except (DocumentServiceError, VectorStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(code=0, message="success", data=result)


@app.get("/api/documents", response_model=ApiResponse[list[DocumentSummary]], response_model_exclude_none=True)
def list_documents() -> ApiResponse[list[DocumentSummary]]:
    """查询个人文档列表。"""
    try:
        result = rag_document_service.list_documents()
    except (DocumentServiceError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(code=0, message="success", data=result)


@app.post("/api/documents/search", response_model=ApiResponse[DocumentSearchResponse], response_model_exclude_none=True)
def search_documents(request: DocumentSearchRequest) -> ApiResponse[DocumentSearchResponse]:
    """检索个人文档 chunks。"""
    try:
        result = rag_document_service.search_documents(request.query, request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (DocumentServiceError, VectorStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(code=0, message="success", data=result)


@app.delete("/api/documents/{document_id}", response_model=ApiResponse[DocumentDeleteResponse])
def delete_document(document_id: str) -> ApiResponse[DocumentDeleteResponse]:
    """删除个人文档、原文件、解析文本和向量。"""
    try:
        result = rag_document_service.delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DocumentServiceError, VectorStoreError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(code=0, message="success", data=result)


def format_sse_event(event: str, payload: dict) -> str:
    """格式化一个 SSE 事件帧。

    @param event: SSE 事件名，例如 `on_chat_model_stream` 或 `agent_done`。
    @param payload: 事件数据，会被序列化到 `data:` 行。
    @return: 符合 SSE 协议的文本帧。
    """
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"
