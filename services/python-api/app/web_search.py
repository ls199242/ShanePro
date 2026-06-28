"""Web 搜索工具。

本模块把不同搜索 API 的响应规整为统一结构，供 AI 对话服务调用。
当前不引入第三方 HTTP 依赖，使用标准库 `urllib` 发起请求。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_MAX_RESULTS = 5


class WebSearchError(RuntimeError):
    """Web 搜索工具调用失败。"""


@dataclass(frozen=True)
class WebSearchResult:
    """统一的单条搜索结果。"""

    title: str
    url: str
    snippet: str

    def model_dump(self) -> dict[str, str]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class WebSearchResponse:
    """统一的搜索工具响应。"""

    provider: str
    query: str
    results: list[WebSearchResult]

    def model_dump(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "provider": self.provider,
            "query": self.query,
            "results": [item.model_dump() for item in self.results],
        }


class WebSearchTool:
    """Web 搜索工具封装。

    配置优先级为：当前进程环境变量 > `~/.claude/settings.json`。
    支持 provider：
    - `tavily`: 使用 `TAVILY_API_KEY`；
    - `brave`: 使用 `BRAVE_SEARCH_API_KEY`；
    - `serper`: 使用 `SERPER_API_KEY`。
    """

    async def search(self, query: str) -> WebSearchResponse:
        """执行一次 Web 搜索。

        @param query: 搜索关键词，不能为空。
        @return: 统一搜索结果。
        @raises WebSearchError: 未配置 provider、token 缺失、网络失败或响应异常时抛出。
        """
        search_query = query.strip()
        if not search_query:
            raise WebSearchError("搜索关键词不能为空")

        config = load_web_search_config()
        return await asyncio.to_thread(self._search_sync, search_query, config)

    def _search_sync(self, query: str, config: dict[str, str]) -> WebSearchResponse:
        """同步执行搜索请求。

        该方法运行在线程池中，避免阻塞 FastAPI 事件循环。
        """
        provider = config.get("WEB_SEARCH_PROVIDER", "tavily").strip().lower()
        max_results = parse_positive_int(config.get("WEB_SEARCH_MAX_RESULTS"), DEFAULT_MAX_RESULTS)

        if provider == "tavily":
            return self._search_tavily(query, config, max_results)
        if provider == "brave":
            return self._search_brave(query, config, max_results)
        if provider == "serper":
            return self._search_serper(query, config, max_results)
        raise WebSearchError(f"暂不支持的 WEB_SEARCH_PROVIDER: {provider}")

    def _search_tavily(self, query: str, config: dict[str, str], max_results: int) -> WebSearchResponse:
        """调用 Tavily Search API。"""
        api_key = config.get("TAVILY_API_KEY", "")
        if not api_key:
            raise WebSearchError("未配置 TAVILY_API_KEY")

        body = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        data = request_json(
            "https://api.tavily.com/search",
            method="POST",
            headers={"Content-Type": "application/json"},
            payload=body,
        )
        results = [
            WebSearchResult(
                title=string_value(item.get("title")),
                url=string_value(item.get("url")),
                snippet=string_value(item.get("content") or item.get("snippet")),
            )
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]
        return WebSearchResponse(provider="tavily", query=query, results=compact_results(results))

    def _search_brave(self, query: str, config: dict[str, str], max_results: int) -> WebSearchResponse:
        """调用 Brave Search API。"""
        api_key = config.get("BRAVE_SEARCH_API_KEY", "")
        if not api_key:
            raise WebSearchError("未配置 BRAVE_SEARCH_API_KEY")

        params = urllib.parse.urlencode({"q": query, "count": max_results})
        data = request_json(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            method="GET",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            payload=None,
        )
        web_data = data.get("web", {})
        raw_results = web_data.get("results", []) if isinstance(web_data, dict) else []
        results = [
            WebSearchResult(
                title=string_value(item.get("title")),
                url=string_value(item.get("url")),
                snippet=string_value(item.get("description")),
            )
            for item in raw_results
            if isinstance(item, dict)
        ]
        return WebSearchResponse(provider="brave", query=query, results=compact_results(results))

    def _search_serper(self, query: str, config: dict[str, str], max_results: int) -> WebSearchResponse:
        """调用 Serper Google Search API。"""
        api_key = config.get("SERPER_API_KEY", "")
        if not api_key:
            raise WebSearchError("未配置 SERPER_API_KEY")

        data = request_json(
            "https://google.serper.dev/search",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            },
            payload={"q": query, "num": max_results},
        )
        results = [
            WebSearchResult(
                title=string_value(item.get("title")),
                url=string_value(item.get("link")),
                snippet=string_value(item.get("snippet")),
            )
            for item in data.get("organic", [])
            if isinstance(item, dict)
        ]
        return WebSearchResponse(provider="serper", query=query, results=compact_results(results))


def build_web_search_context(response: WebSearchResponse) -> str:
    """把搜索结果整理成可注入模型上下文的文本。"""
    if not response.results:
        return f"Web 搜索工具未找到与 `{response.query}` 相关的结果。"

    lines = [f"Web 搜索结果，provider={response.provider}，query={response.query}："]
    for index, item in enumerate(response.results, start=1):
        lines.append(f"{index}. {item.title}\n   URL: {item.url}\n   摘要: {item.snippet}")
    return "\n".join(lines)


def request_json(url: str, method: str, headers: dict[str, str], payload: dict[str, Any] | None) -> dict[str, Any]:
    """发起 HTTP 请求并解析 JSON 响应。"""
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WebSearchError(f"Web 搜索接口返回 HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise WebSearchError(f"Web 搜索网络请求失败: {exc.reason}") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise WebSearchError("Web 搜索接口返回了非 JSON 响应") from exc
    if not isinstance(parsed, dict):
        raise WebSearchError("Web 搜索接口返回结构异常")
    return parsed


def load_web_search_config() -> dict[str, str]:
    """读取 Web 搜索配置。"""
    config = load_config_from_settings()
    for key, value in os.environ.items():
        if key.startswith("WEB_SEARCH_") or key in {"TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY"}:
            config[key] = value
    return config


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


def compact_results(results: list[WebSearchResult]) -> list[WebSearchResult]:
    """过滤空结果，避免把不可用链接注入模型上下文。"""
    return [item for item in results if item.title and item.url]


def parse_positive_int(value: str | None, default: int) -> int:
    """解析正整数配置。"""
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def string_value(value: Any) -> str:
    """把任意值规整为字符串。"""
    return value.strip() if isinstance(value, str) else ""


web_search_tool = WebSearchTool()
