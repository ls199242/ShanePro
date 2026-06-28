"""AI 问答服务。

本模块负责三件事：
- 读取 Anthropic 兼容模型配置；
- 通过 LangChain Agent 组织模型调用和工具调用；
- 使用 LangGraph checkpointer 维护内存会话，并把 Agent 流式事件转发给前端。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.rag_tool import build_personal_knowledge_agent_tool
from app.schemas import ChatMessage, ChatResponse, ToolCallRecord
from app.web_search import WebSearchError, web_search_tool

THINKING_KEYS = ("thinking", "reasoning", "reasoning_content", "reasoning_text")
THINKING_TYPES = ("thinking", "thinking_delta", "reasoning", "reasoning_delta")
DEFAULT_TIMEZONE = "Asia/Shanghai"
AGENT_EVENT_NAMES = {
    "on_chat_model_stream",
    "on_tool_start",
    "on_tool_end",
    "on_tool_error",
}
SYSTEM_PROMPT = (
    "你是 Shane 个人站点中的 AI 问答助手。回答要简洁、准确。"
    "你可以自主决定是否调用工具。"
)
WEB_SEARCH_SYSTEM_PROMPT = (
    "当问题需要最新信息、官网链接、新闻、价格、版本或外部资料时，调用 web_search 工具。"
    "如果使用了 Web 搜索结果，请优先基于搜索结果回答，并在需要时引用结果中的 URL。"
)
NO_WEB_SEARCH_SYSTEM_PROMPT = (
    "本轮未启用联网搜索工具。不要声称已经联网或查询了外部网页；"
    "如果问题依赖最新信息，请说明当前未启用联网搜索。"
)
PERSONAL_KNOWLEDGE_SYSTEM_PROMPT = (
    "当问题涉及用户上传的个人文档、笔记、简历、合同、资料、文件内容或私有知识时，"
    "调用 personal_knowledge_search 工具。"
    "回答个人文档相关问题时优先基于检索结果；如果没有找到可靠依据，请明确说明。"
)
NO_PERSONAL_KNOWLEDGE_SYSTEM_PROMPT = (
    "本轮未启用个人文档 RAG 工具。不要声称已经查询了用户上传文档；"
    "如果问题依赖个人文档内容，请说明当前未启用个人文档检索。"
)
CURRENT_TIME_SYSTEM_PROMPT = (
    "当前时间：{current_time}。"
    "回答涉及今天、昨天、明天、当前、最新、截止时间等相对时间时，必须以这个时间为准。"
)


class AiChatService:
    """基于 LangChain Agent 的 AI 对话服务。

    当前版本使用 `InMemorySaver` 保存会话状态，适合本地个人站点使用。
    服务重启后会话会丢失；后续需要持久化时再替换 checkpointer。
    """

    def __init__(self) -> None:
        self._agents: dict[tuple[bool, bool], Any] = {}
        self._checkpointer: Any | None = None
        self._agent_lock = asyncio.Lock()

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        web_search_enabled: bool = True,
        rag_enabled: bool = True,
    ) -> ChatResponse:
        """执行一次非流式 Agent 对话。

        @param message: 用户输入内容，不能为空。
        @param session_id: 后端会话 ID；为空时创建新会话。
        @param web_search_enabled: 是否允许 Agent 在本轮调用联网搜索工具。
        @param rag_enabled: 是否允许 Agent 在本轮调用个人文档 RAG 工具。
        @return: 模型回复、thinking 内容、工具调用记录和会话历史。
        @raises ValueError: 用户输入为空时抛出。
        @raises RuntimeError: 模型配置缺失或 Agent 调用失败时抛出。
        """
        content = message.strip()
        if not content:
            raise ValueError("message cannot be empty")

        current_session_id = session_id or uuid4().hex
        agent = await self._get_agent(web_search_enabled, rag_enabled)
        config = build_agent_config(current_session_id)
        result = await agent.ainvoke({"messages": [{"role": "user", "content": content}]}, config=config)
        messages = get_agent_messages(result)
        turn_messages = get_current_turn_messages(messages, content)
        answer, thinking = extract_final_assistant_parts(turn_messages or messages)

        return ChatResponse(
            session_id=current_session_id,
            answer=answer,
            thinking=thinking or None,
            tools=extract_tool_records(turn_messages) or None,
            history=messages_to_chat_history(messages),
        )

    async def stream_chat(
        self,
        message: str,
        session_id: str | None = None,
        web_search_enabled: bool = True,
        rag_enabled: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行一次流式 Agent 对话。

        事件约定：
        - `session`: 返回本轮使用的后端 session_id；
        - LangChain 原生事件：`on_chat_model_stream`、`on_tool_start`、`on_tool_end`、`on_tool_error`；
        - `agent_done`: Agent 流结束后的最终响应、工具记录和会话历史。
        - `web_search_enabled=false`: 本轮 Agent 不注册 `web_search` 工具。
        - `rag_enabled=false`: 本轮 Agent 不注册 `personal_knowledge_search` 工具。
        """
        content = message.strip()
        if not content:
            raise ValueError("message cannot be empty")

        current_session_id = session_id or uuid4().hex
        yield {"event": "session", "session_id": current_session_id}

        agent = await self._get_agent(web_search_enabled, rag_enabled)
        config = build_agent_config(current_session_id)
        stream_answer = ""
        stream_thinking = ""

        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": content}]},
            config=config,
            version="v2",
        ):
            normalized_event = normalize_agent_event(event)
            if not normalized_event:
                continue

            if normalized_event["event"] == "on_chat_model_stream":
                stream_answer += normalized_event.get("data", {}).get("text", "")
                stream_thinking += normalized_event.get("data", {}).get("thinking", "")

            yield normalized_event

        state = await agent.aget_state(config)
        messages = get_agent_messages(state.values)
        turn_messages = get_current_turn_messages(messages, content)
        answer, thinking = extract_final_assistant_parts(turn_messages or messages)

        yield {
            "event": "agent_done",
            "session_id": current_session_id,
            "answer": answer or stream_answer,
            "thinking": thinking or stream_thinking,
            "tools": [item.model_dump(exclude_none=True) for item in extract_tool_records(turn_messages)],
            "history": [item.model_dump(exclude_none=True) for item in messages_to_chat_history(messages)],
        }

    async def _get_agent(self, web_search_enabled: bool, rag_enabled: bool) -> Any:
        """按联网搜索和 RAG 开关懒加载 LangChain Agent。

        多个 Agent 共享同一个 InMemorySaver，避免同一 session 在开关切换后丢失历史。
        """
        agent_key = (web_search_enabled, rag_enabled)
        if agent_key in self._agents:
            return self._agents[agent_key]

        async with self._agent_lock:
            if self._checkpointer is None:
                self._checkpointer = build_checkpointer()
            if agent_key not in self._agents:
                self._agents[agent_key] = build_agent(web_search_enabled, rag_enabled, self._checkpointer)
        return self._agents[agent_key]


def build_agent(web_search_enabled: bool = True, rag_enabled: bool = True, checkpointer: Any | None = None) -> Any:
    """创建 LangChain Agent。"""
    from langchain.agents import create_agent

    return create_agent(
        model=build_chat_model(),
        tools=build_agent_tools(web_search_enabled, rag_enabled),
        middleware=[build_dynamic_system_prompt(web_search_enabled, rag_enabled)],
        checkpointer=checkpointer or build_checkpointer(),
    )


def build_checkpointer() -> Any:
    """创建 LangGraph 内存 checkpointer。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def build_agent_tools(web_search_enabled: bool, rag_enabled: bool = True) -> list[Any]:
    """根据本轮工具开关返回 Agent 工具列表。"""
    tools = []
    if rag_enabled:
        tools.append(build_personal_knowledge_agent_tool())
    if web_search_enabled:
        tools.append(build_web_search_agent_tool())
    return tools


def build_dynamic_system_prompt(web_search_enabled: bool, rag_enabled: bool = True) -> Any:
    """创建每次模型调用前动态生成系统提示词的 middleware。"""
    from langchain.agents.middleware import dynamic_prompt

    @dynamic_prompt
    def current_system_prompt(_request: Any) -> str:
        return build_system_prompt(web_search_enabled, rag_enabled)

    return current_system_prompt


def build_system_prompt(
    web_search_enabled: bool,
    rag_enabled: bool = True,
    current_time: datetime | None = None,
) -> str:
    """根据本轮工具开关和当前时间生成系统提示词。"""
    time_prompt = CURRENT_TIME_SYSTEM_PROMPT.format(
        current_time=format_current_time(current_time or get_current_time()),
    )
    base_prompt = SYSTEM_PROMPT + time_prompt
    base_prompt += PERSONAL_KNOWLEDGE_SYSTEM_PROMPT if rag_enabled else NO_PERSONAL_KNOWLEDGE_SYSTEM_PROMPT
    if web_search_enabled:
        return base_prompt + WEB_SEARCH_SYSTEM_PROMPT
    return base_prompt + NO_WEB_SEARCH_SYSTEM_PROMPT


def get_current_time() -> datetime:
    """读取当前时间，默认使用 Asia/Shanghai，可通过 AI_TIMEZONE 覆盖。"""
    settings_env = load_config_from_settings()
    time_zone_name = os.environ.get("AI_TIMEZONE") or settings_env.get("AI_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return datetime.now(ZoneInfo(time_zone_name))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def format_current_time(current_time: datetime) -> str:
    """把当前时间格式化成模型容易理解的中文提示。"""
    timezone_name = getattr(current_time.tzinfo, "key", None) or current_time.tzname() or "local"
    timezone_abbr = current_time.tzname()
    formatted = current_time.strftime("%Y-%m-%d %H:%M:%S")
    if timezone_abbr:
        return f"{formatted} {timezone_abbr} ({timezone_name})"
    return f"{formatted} ({timezone_name})"


def build_chat_model() -> Any:
    """创建 Anthropic 兼容 ChatModel。"""
    from langchain_anthropic import ChatAnthropic

    base_url, api_key, model = load_model_config()
    if not api_key:
        raise RuntimeError("未找到 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY")

    max_tokens, thinking_config = load_generation_config()
    llm_args: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "max_tokens": max_tokens,
    }
    # 部分 Anthropic 兼容服务不支持 thinking 参数，可通过 AI_THINKING_ENABLED=false 关闭。
    if thinking_config:
        llm_args["thinking"] = thinking_config
    return ChatAnthropic(**llm_args)


def build_web_search_agent_tool() -> Any:
    """把现有 WebSearchTool 包装成 LangChain tool。"""
    from langchain_core.tools import tool

    @tool(
        "web_search",
        description=(
            "Search the web for fresh external information. "
            "Use this for latest versions, official links, news, prices, releases, or facts likely to change."
        ),
    )
    async def web_search(query: str) -> str:
        """Search the web and return normalized JSON results."""
        try:
            response = await web_search_tool.search(query)
        except WebSearchError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "query": query,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "status": "success",
                **response.model_dump(),
            },
            ensure_ascii=False,
        )

    return web_search


def build_agent_config(session_id: str) -> dict[str, dict[str, str]]:
    """构造 LangGraph checkpointer 使用的 thread_id 配置。"""
    return {"configurable": {"thread_id": session_id}}


def normalize_agent_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """把 LangChain event 规整为可通过 SSE 发送的字典。"""
    event_name = string_value(event.get("event"))
    if event_name not in AGENT_EVENT_NAMES:
        return None

    data = serialize_jsonable(event.get("data", {}))
    if event_name == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk") if isinstance(event.get("data"), dict) else None
        text = extract_text_content(getattr(chunk, "content", ""))
        thinking = extract_thinking_content(getattr(chunk, "content", "")) or extract_chunk_thinking_metadata(chunk)
        data["text"] = text
        data["thinking"] = thinking

    return {
        "event": event_name,
        "name": string_value(event.get("name")),
        "data": data,
        "metadata": serialize_metadata(event.get("metadata", {})),
    }


def serialize_metadata(metadata: Any) -> dict[str, Any]:
    """只保留前端调试有价值的 LangChain metadata。"""
    if not isinstance(metadata, dict):
        return {}
    allowed_keys = ("thread_id", "langgraph_step", "langgraph_node", "langgraph_triggers")
    return {key: serialize_jsonable(metadata[key]) for key in allowed_keys if key in metadata}


def serialize_jsonable(value: Any) -> Any:
    """把 LangChain message/chunk/tool 数据转换成 JSON 兼容结构。"""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [serialize_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return serialize_jsonable(value.model_dump())
    if hasattr(value, "type") and hasattr(value, "content"):
        result = {
            "type": string_value(getattr(value, "type", "")),
            "content": serialize_jsonable(getattr(value, "content", "")),
        }
        if getattr(value, "name", None):
            result["name"] = getattr(value, "name")
        if getattr(value, "tool_calls", None):
            result["tool_calls"] = serialize_jsonable(getattr(value, "tool_calls"))
        if getattr(value, "tool_call_id", None):
            result["tool_call_id"] = getattr(value, "tool_call_id")
        if getattr(value, "status", None):
            result["status"] = getattr(value, "status")
        return result
    return str(value)


def get_agent_messages(result: Any) -> list[Any]:
    """从 Agent invoke/state 结果中读取 messages。"""
    if isinstance(result, dict):
        messages = result.get("messages", [])
        return messages if isinstance(messages, list) else []
    messages = getattr(result, "messages", [])
    return messages if isinstance(messages, list) else []


def get_current_turn_messages(messages: list[Any], user_content: str) -> list[Any]:
    """截取当前用户消息之后的本轮 Agent 消息。"""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message_role(message) == "user" and extract_text_content(getattr(message, "content", "")) == user_content:
            return messages[index + 1 :]
    return messages


def messages_to_chat_history(messages: list[Any]) -> list[ChatMessage]:
    """把 LangChain message 列表转换为前端需要的历史消息。"""
    history: list[ChatMessage] = []
    for message in messages:
        role = message_role(message)
        if role not in {"user", "assistant"}:
            continue
        content = extract_text_content(getattr(message, "content", ""))
        thinking = extract_thinking_content(getattr(message, "content", ""))
        # 跳过只包含 tool_calls、没有可展示内容的 assistant 中间消息。
        if role == "assistant" and not content and getattr(message, "tool_calls", None):
            continue
        history.append(ChatMessage(role=role, content=content, thinking=thinking or None))
    return history[-20:]


def extract_final_assistant_parts(messages: list[Any]) -> tuple[str, str]:
    """提取本轮最后一条 assistant 正式回复和 thinking。"""
    for message in reversed(messages):
        if message_role(message) != "assistant":
            continue
        if getattr(message, "tool_calls", None) and not extract_text_content(getattr(message, "content", "")):
            continue
        return (
            extract_text_content(getattr(message, "content", "")),
            extract_thinking_content(getattr(message, "content", "")),
        )
    return "", ""


def extract_tool_records(messages: list[Any]) -> list[ToolCallRecord]:
    """从本轮 LangChain messages 中提取工具调用记录。"""
    tool_calls: dict[str, ToolCallRecord] = {}
    records: list[ToolCallRecord] = []

    for message in messages:
        for call in getattr(message, "tool_calls", []) or []:
            call_id = string_value(call.get("id"))
            record = ToolCallRecord(
                name=string_value(call.get("name")) or "unknown",
                status="running",
                input=call.get("args") if isinstance(call.get("args"), dict) else {},
            )
            if call_id:
                tool_calls[call_id] = record
            records.append(record)

        if message_role(message) != "tool":
            continue

        tool_call_id = string_value(getattr(message, "tool_call_id", ""))
        output = parse_json_if_possible(getattr(message, "content", ""))
        status = "error" if isinstance(output, dict) and output.get("status") == "error" else "success"
        error = output.get("error") if isinstance(output, dict) and isinstance(output.get("error"), str) else None
        existing = tool_calls.get(tool_call_id)
        updated = ToolCallRecord(
            name=existing.name if existing else string_value(getattr(message, "name", "")) or "unknown",
            status=status,
            input=existing.input if existing else {},
            output=output if status == "success" else None,
            error=error,
        )
        if existing and existing in records:
            records[records.index(existing)] = updated
        else:
            records.append(updated)

    return [record for record in records if record.status != "running"]


def message_role(message: Any) -> str:
    """把 LangChain message type 规整为前端 role。"""
    message_type = string_value(getattr(message, "type", ""))
    if message_type == "human":
        return "user"
    if message_type == "ai":
        return "assistant"
    return message_type


def parse_json_if_possible(value: Any) -> Any:
    """工具输出优先按 JSON 解析，失败时保留原文本。"""
    if not isinstance(value, str):
        return serialize_jsonable(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def extract_text_content(content: Any) -> str:
    """提取可展示的正式回复文本。

    LangChain/Anthropic 的 content 可能是字符串、content block 列表或对象。
    本方法只返回正式回复，不混入 thinking。
    """
    text, _ = extract_content_parts(content)
    return text


def extract_thinking_content(content: Any) -> str:
    """提取模型 thinking / reasoning 文本。"""
    _, thinking = extract_content_parts(content)
    return thinking


def extract_content_parts(content: Any) -> tuple[str, str]:
    """把模型 content 拆成正式回复和 thinking 两个通道。"""
    if isinstance(content, str):
        return content, ""

    if isinstance(content, list):
        text_parts = []
        thinking_parts = []
        for item in content:
            text, thinking = extract_content_parts(item)
            text_parts.append(text)
            thinking_parts.append(thinking)
        return "".join(text_parts), "".join(thinking_parts)

    if isinstance(content, dict):
        block_type = str(content.get("type", ""))
        thinking = first_string_value(content, THINKING_KEYS)
        if block_type in THINKING_TYPES or thinking:
            return "", thinking or string_value(content.get("text"))

        if "delta" in content:
            delta_text, delta_thinking = extract_content_parts(content["delta"])
            text = string_value(content.get("text"))
            return f"{text}{delta_text}", delta_thinking

        return string_value(content.get("text")), ""

    block_type = str(getattr(content, "type", ""))
    thinking = first_attr_value(content, THINKING_KEYS)
    if block_type in THINKING_TYPES or thinking:
        return "", thinking or string_value(getattr(content, "text", None))

    text = getattr(content, "text", None)
    return text if isinstance(text, str) else "", ""


def extract_chunk_thinking_metadata(chunk: Any) -> str:
    """从 AIMessageChunk 元数据中提取 thinking。"""
    if chunk is None:
        return ""
    thinking_parts = []
    for attr_name in ("additional_kwargs", "response_metadata"):
        value = getattr(chunk, attr_name, None)
        if isinstance(value, dict):
            thinking_parts.append(first_string_value(value, THINKING_KEYS))
    return "".join(thinking_parts)


def first_string_value(source: dict[str, Any], keys: tuple[str, ...]) -> str:
    """按候选 key 顺序读取第一个字符串值。"""
    for key in keys:
        value = source.get(key)
        text = string_value(value)
        if text:
            return text
    return ""


def first_attr_value(source: Any, keys: tuple[str, ...]) -> str:
    """按候选属性名顺序读取第一个字符串值。"""
    for key in keys:
        text = string_value(getattr(source, key, None))
        if text:
            return text
    return ""


def string_value(value: Any) -> str:
    """把模型 SDK 返回值规整为字符串；非字符串统一忽略。"""
    return value if isinstance(value, str) else ""


def load_config_from_settings() -> dict[str, str]:
    """从 `~/.claude/settings.json` 读取模型配置。"""
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        with settings_path.open(encoding="utf-8") as file:
            settings = json.load(file)
            env = settings.get("env", {})
            if isinstance(env, dict):
                return {str(key): str(value) for key, value in env.items()}
    return {}


def load_model_config() -> tuple[str, str | None, str]:
    """加载模型地址、鉴权 token 和模型名。"""
    settings_env = load_config_from_settings()
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or settings_env.get(
        "ANTHROPIC_BASE_URL",
        "https://token-plan-cn.xiaomimimo.com/anthropic",
    )
    api_key = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or settings_env.get("ANTHROPIC_AUTH_TOKEN")
        or settings_env.get("ANTHROPIC_API_KEY")
    )
    model = os.environ.get("ANTHROPIC_MODEL") or settings_env.get(
        "ANTHROPIC_MODEL",
        "mimo-v2.5-pro",
    )
    return base_url, api_key, model


def load_generation_config() -> tuple[int, dict[str, Any] | None]:
    """加载生成参数。"""
    settings_env = load_config_from_settings()
    max_tokens = parse_int_config("AI_MAX_TOKENS", settings_env, 4096)
    thinking_enabled = parse_bool_config("AI_THINKING_ENABLED", settings_env, True)
    if not thinking_enabled:
        return max_tokens, None

    budget_tokens = parse_int_config("AI_THINKING_BUDGET_TOKENS", settings_env, 1024)
    if budget_tokens >= max_tokens:
        budget_tokens = max(256, max_tokens // 2)
    return max_tokens, {"type": "enabled", "budget_tokens": budget_tokens}


def parse_int_config(name: str, settings_env: dict[str, str], default: int) -> int:
    """读取正整数配置，非法值回退到默认值。"""
    raw_value = os.environ.get(name) or settings_env.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def parse_bool_config(name: str, settings_env: dict[str, str], default: bool) -> bool:
    """读取布尔配置。"""
    raw_value = os.environ.get(name) or settings_env.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


chat_service = AiChatService()
