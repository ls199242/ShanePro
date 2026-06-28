"""个人知识库 LangChain tool。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.document_service import rag_document_service


def build_personal_knowledge_agent_tool() -> Any:
    """创建个人知识库检索工具。"""
    from langchain_core.tools import tool

    @tool(
        "personal_knowledge_search",
        description=(
            "Search the user's uploaded personal documents. "
            "Use this when the question mentions uploaded documents, personal notes, resume, contracts, files, or private materials."
        ),
    )
    async def personal_knowledge_search(query: str) -> str:
        """Search uploaded personal documents and return normalized JSON results."""
        try:
            response = await asyncio.to_thread(rag_document_service.search_documents, query, None)
        except Exception as exc:
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

    return personal_knowledge_search
