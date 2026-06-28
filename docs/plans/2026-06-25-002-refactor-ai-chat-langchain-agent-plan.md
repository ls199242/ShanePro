---
title: "refactor: Organize AI chat with LangChain agent tools"
type: "refactor"
date: "2026-06-25"
---

# refactor: Organize AI chat with LangChain agent tools

## Summary

将 Python AI 聊天从“手写工具触发 + 手写模型上下文拼接”改为 LangChain Agent 架构。Agent 自主决定是否调用 `web_search`，会话记忆由 LangGraph `InMemorySaver` 按 `session_id` 维护，前端改为消费 LangChain stream events。

## Key Changes

- `AiChatService` 使用 `create_agent(model=ChatAnthropic(...), tools=[web_search], checkpointer=InMemorySaver())`。
- `web_search` 作为 LangChain tool 注册，工具描述交给模型判断何时调用。
- `/api/chat/stream` 输出 `on_chat_model_stream`、`on_tool_start`、`on_tool_end`、`on_tool_error` 等 LangChain 事件，并在结束时补充 `agent_done`。
- 前端 `AiChatPanel` 按 LangChain 事件更新回复文本、thinking、工具调用入参/出参和最终交互记录。
- README 中的搜索说明从“关键词触发”改为“Agent 自主决定调用工具”。

## Test Plan

- Python:
  - `services/python-api/.venv/bin/python -m pytest`
  - `services/python-api/.venv/bin/python -m compileall app tests`
  - 构建 `build_web_search_agent_tool()` 和 `build_agent()` 做 smoke test。
- Frontend:
  - `apps/frontend ./node_modules/.bin/vitest run`
  - `apps/frontend ./node_modules/.bin/vite build`
- Java:
  - `services/java-api mvn test`

## Assumptions

- 继续使用内存 checkpointer，服务重启后会话丢失。
- `web_search` provider 配置沿用 `WEB_SEARCH_PROVIDER`、`TAVILY_API_KEY`、`BRAVE_SEARCH_API_KEY`、`SERPER_API_KEY`。
- 前端不保持旧 `delta/tool_start/done` 协议兼容，统一处理 LangChain `on_*` 事件和自定义 `agent_done`。
