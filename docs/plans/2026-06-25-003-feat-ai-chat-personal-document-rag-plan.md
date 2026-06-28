---
title: "feat: Add personal document RAG to AI chat"
type: "feat"
date: "2026-06-25"
---

# feat: Add personal document RAG to AI chat

## Summary

为现有 AI 问答加入个人文档 RAG。首版先完成文档上传、文本抽取、切分、BGE-M3 本地向量化、写入 Docker pgvector，并提供文档列表与检索能力。之后再把检索能力作为 LangChain Agent tool 接入现有 AI 问答，让模型在回答个人文档相关问题时调用个人知识库。

当前模型接口可能不支持 OpenAI embeddings，因此本计划不依赖 `client.embeddings.create`。Embedding 首版采用本地 `BAAI/bge-m3` dense embedding，向量维度按 BGE-M3 dense 输出规划为 `1024`，存储层使用 PostgreSQL + pgvector。

---

## Current Context

当前项目已有：

- Vue AI 问答页，能展示 LangChain 工具调用过程和工具结果。
- FastAPI Python API，负责 AI 对话接口。
- `services/python-api/app/ai_chat.py` 已使用 LangChain Agent，并已接入 `web_search` tool。
- `services/python-api/app/main.py` 只承担 HTTP 路由、统一响应包装和异常转换。
- Python 依赖当前只有 FastAPI、LangChain、LangChain Anthropic 和 pytest，尚未包含向量库、文本切分、PDF 解析或 embedding provider。

因此 RAG 应先落在 `services/python-api`，再通过现有 Agent tool 机制接入聊天。

---

## Requirements

- R1. 支持上传个人文档，首版文件类型为 `.txt`、`.md`、`.pdf`。
- R2. 上传文件不直接交给前端处理，文件解析、切分、向量化全部在 Python API 后端完成。
- R3. 文档切分使用 LangChain 官方 text splitter，首版采用 `RecursiveCharacterTextSplitter`。
- R4. Embedding 使用本地 BGE-M3 dense embedding，不依赖当前 Anthropic/OpenAI-compatible 聊天接口。
- R5. 向量库存储使用用户本机 Docker 中的 PostgreSQL + pgvector。
- R6. 文档元数据、处理状态、错误信息要可查询，便于前端展示上传进度和失败原因。
- R7. 文档摄取失败不能影响 AI 聊天基础功能。
- R8. 检索结果必须保留来源信息：`document_id`、文件名、chunk 序号、文本片段。
- R9. 后续接入 AI 问答时，RAG 作为新的 LangChain tool，例如 `personal_knowledge_search`。
- R10. 不在首版引入鉴权、多用户隔离、后台任务队列或复杂权限模型。
- R11. 文件导入必须基于 MD5 做判重；重复文件直接返回已有文档记录，不重复解析、切分、向量化或写入向量库。
- R12. 解析后的完整纯文本必须落本地文件，文档元数据中保存原始上传文件路径和解析文本路径。

---

## Key Technical Decisions

- KTD1. **Embedding 使用 BGE-M3 本地 dense 模式：** 避免依赖当前代理 URL 是否支持 embeddings。BGE-M3 对中英混合文档更友好，首版只使用 dense vector，暂不接 sparse / ColBERT。
- KTD2. **向量库使用 pgvector：** 用户本机已有 Docker pgvector，不再使用 Chroma。本项目统一通过 `langchain-postgres` 封装向量写入与相似度检索。
- KTD3. **pgvector collection 不混用 embedding 模型：** BGE-M3 dense 输出维度为 `1024`。后续如果切换 embedding 模型，需要新建 collection 并重新向量化。
- KTD4. **文本切分用 RecursiveCharacterTextSplitter：** 它是 LangChain 常用通用 splitter。首版配置建议 `chunk_size=1000`、`chunk_overlap=150`，后续根据问答质量调整。
- KTD5. **PDF 解析先用 `pypdf`：** 为 `.pdf` 抽取纯文本即可。复杂版式、扫描件 OCR、表格结构化先不做。
- KTD6. **文档元数据放同一个 PostgreSQL：** pgvector 存 chunk 向量和 metadata；另建轻量业务表记录文档状态、MD5、chunk 数和错误信息。
- KTD7. **首版同步摄取：** 上传后同步完成解析、切分、向量化和入库。个人文档体量较小时更简单；大文件或批量上传后再改后台任务。
- KTD8. **删除文档需要同步删除向量：** 删除逻辑按 `document_id` 删除业务表和向量记录。执行前端删除操作时需要二次确认。
- KTD9. **文件导入使用 MD5 判重：** MD5 只用于本地个人文档的重复文件识别，不作为安全完整性校验。上传后先计算文件 MD5，再查 `rag_documents.md5`；若命中已有记录且状态为 `ready`，直接返回已有文档，避免重复入库。
- KTD10. **完整解析文本单独本地持久化：** pgvector 只存 chunk 文本、向量和 chunk metadata；解析后的完整纯文本写入 `data/parsed/{document_id}.txt`，便于后续重切分、重建向量和排查解析质量。

---

## High-Level Design

```mermaid
flowchart TB
  UI[Vue AI Chat / Document Panel] --> UploadAPI[FastAPI /api/documents/upload]
  UploadAPI --> FileStore[Local uploads directory]
  UploadAPI --> Parser[Document Parser txt/md/pdf]
  Parser --> Splitter[RecursiveCharacterTextSplitter]
  Splitter --> Embedding[BGE-M3 local embeddings]
  Embedding --> PGVector[(PostgreSQL + pgvector)]
  UploadAPI --> Metadata[(rag_documents table)]

  ChatUI[Vue AI Chat] --> ChatAPI[FastAPI /api/chat/stream]
  ChatAPI --> Agent[LangChain Agent]
  Agent --> RagTool[personal_knowledge_search tool]
  RagTool --> PGVector
  Agent --> LLM[Current Anthropic-compatible chat model]
```

RAG 摄取链路和聊天链路分开。上传文档时只负责把文档变成可检索的 chunks；聊天时由 Agent 按问题决定是否调用个人知识库检索工具。

---

## Data Model

### PostgreSQL extension

目标数据库需要启用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Business metadata table

计划新增业务表：

```sql
CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    md5 TEXT NOT NULL,
    original_path TEXT NOT NULL,
    parsed_text_path TEXT,
    status TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_rag_documents_md5 ON rag_documents (md5);
CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag_documents (status);
```

路径约定：

- `original_path`: 原始上传文件的本地保存路径。
- `parsed_text_path`: 解析后的完整纯文本本地保存路径；解析成功后写入，失败时可为空。

`status` 首版取值：

- `processing`
- `ready`
- `failed`

向量表由 `langchain-postgres` 管理。每个 chunk metadata 至少包含：

```json
{
  "document_id": "uuid",
  "filename": "example.pdf",
  "chunk_index": 0,
  "source": "example.pdf"
}
```

---

## Python Dependencies

计划新增依赖：

```toml
langchain-postgres
langchain-text-splitters
langchain-huggingface
sentence-transformers
pypdf
psycopg[binary]
```

说明：

- `langchain-text-splitters`: 提供 `RecursiveCharacterTextSplitter`。
- `langchain-huggingface` + `sentence-transformers`: 加载 `BAAI/bge-m3` 做本地 dense embedding。
- `langchain-postgres`: LangChain PGVector 集成。
- `pypdf`: PDF 文本抽取。
- `psycopg[binary]`: 业务元数据表和 pgvector 连接使用。

如果 macOS Intel 本地安装 PyTorch 或 sentence-transformers 依赖较慢，优先保留 `EmbeddingProvider` 抽象，后续可切到独立 embedding 服务，不影响 API 和 pgvector schema。

---

## Configuration

计划新增配置，优先环境变量，其次读取 `~/.claude/settings.json` 的 `env`：

```bash
export RAG_PGVECTOR_CONNECTION="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"
export RAG_PGVECTOR_COLLECTION="personal_documents_bge_m3"
export RAG_EMBEDDING_MODEL="BAAI/bge-m3"
export RAG_EMBEDDING_DEVICE="cpu"
export RAG_CHUNK_SIZE="1000"
export RAG_CHUNK_OVERLAP="150"
export RAG_RETRIEVAL_TOP_K="5"
export RAG_UPLOAD_DIR="services/python-api/data/uploads"
export RAG_PARSED_TEXT_DIR="services/python-api/data/parsed"
```

`RAG_PGVECTOR_COLLECTION` 名称包含模型语义，避免后续切换 embedding 模型时误用旧 collection。

---

## Backend Modules

计划新增模块：

```text
services/python-api/app/rag_config.py
services/python-api/app/document_parser.py
services/python-api/app/document_chunker.py
services/python-api/app/embedding_service.py
services/python-api/app/vector_store.py
services/python-api/app/document_service.py
services/python-api/app/rag_tool.py
```

职责：

- `rag_config.py`: 读取 pgvector、BGE-M3、切分、上传目录和解析文本目录配置。
- `document_parser.py`: 解析 `.txt`、`.md`、`.pdf` 为纯文本。
- `document_chunker.py`: 基于 `RecursiveCharacterTextSplitter` 生成 chunks。
- `embedding_service.py`: 封装 BGE-M3 embeddings，暴露 `embed_documents` / `embed_query`。
- `vector_store.py`: 封装 LangChain PGVector 写入、检索、删除。
- `document_service.py`: 编排上传、MD5 判重、原始文件保存、完整纯文本落盘、元数据、解析、切分、向量化、状态更新。
- `rag_tool.py`: 把个人知识库检索包装成 LangChain tool。

---

## API Contract

### Upload document

```http
POST /api/documents/upload
Content-Type: multipart/form-data
```

响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "document uuid",
    "filename": "notes.pdf",
    "md5": "file md5",
    "status": "ready",
    "chunk_count": 12,
    "duplicate": false
  }
}
```

导入判重规则：

- 新文件上传后先计算 MD5，再查询 `rag_documents.md5`。
- 若已有记录状态为 `ready`，直接返回已有文档，`duplicate=true`，不重复解析、切分、向量化或写入 pgvector。
- 若已有记录状态为 `processing`，返回已有文档当前状态，`duplicate=true`，不启动第二个摄取流程。
- 若已有记录状态为 `failed`，复用原 `document_id` 重试摄取，状态更新为 `processing`。

### List documents

```http
GET /api/documents
```

响应包含文档 ID、文件名、MD5、大小、原始文件路径、解析文本路径、状态、chunk 数、错误信息和时间。

### Search documents

```http
POST /api/documents/search
Content-Type: application/json
```

请求：

```json
{
  "query": "我的简历里提到过哪些项目？",
  "top_k": 5
}
```

响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "我的简历里提到过哪些项目？",
    "results": [
      {
        "document_id": "document uuid",
        "filename": "resume.pdf",
        "chunk_index": 3,
        "content": "matched chunk text",
        "score": 0.82
      }
    ]
  }
}
```

### Delete document

```http
DELETE /api/documents/{document_id}
```

删除文档元数据、上传文件和对应向量。前端需要二次确认。

---

## RAG Tool Contract

计划新增 Agent tool：`personal_knowledge_search`。

工具入参：

```json
{
  "query": "用户问题或检索关键词"
}
```

工具出参：

```json
{
  "status": "success",
  "query": "用户问题或检索关键词",
  "results": [
    {
      "document_id": "document uuid",
      "filename": "notes.md",
      "chunk_index": 2,
      "content": "chunk text",
      "score": 0.78
    }
  ]
}
```

系统提示词需要补充：

- 当问题涉及“我的文档”“我上传的资料”“简历/笔记/合同/资料中提到”等个人资料时，调用 `personal_knowledge_search`。
- 回答时优先基于检索结果。
- 如果检索结果不足，明确说明“没有在已上传文档中找到可靠依据”。

---

## Implementation Units

### U1. Add RAG dependencies and config

- **Goal:** 引入 pgvector、splitter、BGE-M3 embedding 相关依赖和配置读取。
- **Files:** `services/python-api/pyproject.toml`, `services/python-api/app/rag_config.py`, README。
- **Verification:** 能读取 `RAG_*` 配置；未配置 pgvector 时返回清晰错误。

### U2. Add document metadata storage

- **Goal:** 在 PostgreSQL 中初始化 `rag_documents` 表。
- **Files:** `services/python-api/app/document_service.py` 或独立 repository 模块。
- **Verification:** 能创建文档记录、保存原始文件路径和解析文本路径、更新状态、列出文档、记录失败原因；同一文件重复上传时通过 MD5 命中已有记录。

### U3. Add parser and splitter

- **Goal:** 支持 `.txt`、`.md`、`.pdf` 抽取文本并切分。
- **Files:** `document_parser.py`, `document_chunker.py`。
- **Verification:** 单测覆盖三种格式；解析后的完整纯文本写入 `RAG_PARSED_TEXT_DIR/{document_id}.txt`；空文本、损坏 PDF、超大文件返回明确失败。

### U4. Add BGE-M3 embedding service

- **Goal:** 使用本地 `BAAI/bge-m3` 生成 dense vectors。
- **Files:** `embedding_service.py`。
- **Approach:** 默认用 `HuggingFaceEmbeddings(model_name="BAAI/bge-m3", encode_kwargs={"normalize_embeddings": True})`。
- **Verification:** `embed_query("测试文本")` 返回长度为 `1024` 的向量。

### U5. Add pgvector store wrapper

- **Goal:** 用 LangChain PGVector 写入、检索、按文档删除 chunks。
- **Files:** `vector_store.py`。
- **Verification:** 写入 chunks 后能按 query 检索；删除 document 后不再命中该文档。

### U6. Add document APIs

- **Goal:** 暴露上传、列表、检索、删除接口。
- **Files:** `main.py`, `schemas.py`, `document_service.py`。
- **Verification:** FastAPI tests 覆盖上传成功、MD5 重复上传直接返回已有文档、文件类型不支持、检索成功、删除成功。

### U7. Add frontend document panel

- **Goal:** 在 AI 问答页提供文档上传和文档列表。
- **Files:** `apps/frontend/src/api/services.js`, `apps/frontend/src/components/AiChatPanel.vue`。
- **Verification:** 前端测试覆盖上传、列表展示、失败状态和删除确认。

### U8. Integrate RAG tool into AI chat

- **Goal:** 把 `personal_knowledge_search` 加入 LangChain Agent tools。
- **Files:** `ai_chat.py`, `rag_tool.py`。
- **Verification:** 流式聊天中能展示个人知识库工具调用；`agent_done.tools` 包含检索入参和结果。

### U9. Documentation and local runbook

- **Goal:** README 补充 pgvector Docker、BGE-M3 首次下载、环境变量和验证命令。
- **Files:** `README.md`, `services/python-api/README.md`。
- **Verification:** 按文档能启动 pgvector、上传文档、检索文档、完成 RAG 问答。

---

## Rollout Order

1. 先实现 U1-U5：后端摄取链路闭环，不动聊天逻辑。
2. 再实现 U6：提供 HTTP API，可用 curl 验证上传和检索。
3. 再实现 U7：前端文档上传和文档列表。
4. 最后实现 U8：把 RAG 检索接入 AI 问答工具链。
5. U9 贯穿每个阶段更新，避免配置步骤滞后。

---

## Verification Commands

Python API：

```bash
cd services/python-api
uv sync
uv run pytest
```

手动验证 pgvector：

```bash
psql "$RAG_PGVECTOR_CONNECTION" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

上传验证：

```bash
curl -X POST http://127.0.0.1:8000/api/documents/upload \
  -F "file=@/path/to/notes.md"
```

检索验证：

```bash
curl -X POST http://127.0.0.1:8000/api/documents/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"这份文档讲了什么？","top_k":5}'
```

前端：

```bash
cd apps/frontend
pnpm test
pnpm build
```

---

## Risks and Mitigations

- **BGE-M3 首次下载慢：** 文档说明模型会下载到 Hugging Face 缓存；必要时可提前下载模型。
- **macOS Intel CPU embedding 慢：** 首版个人文档可接受；后续可把 `EmbeddingProvider` 切到独立服务或更小模型。
- **PDF 抽取质量不稳定：** 首版只承诺文本型 PDF；扫描件 OCR 后置。
- **向量维度不匹配：** collection 名包含 embedding 模型；启动时校验 embedding 维度。
- **重复上传：** 通过文件 MD5 做唯一约束；重复文件直接返回已有文档记录，不再重复解析、切分、向量化和写入 pgvector。
- **MD5 碰撞：** 首版仅把 MD5 用作个人本地文件判重，不作为安全校验。若后续涉及外部不可信上传，可同时保留 SHA-256 辅助校验。
- **删除误操作：** 前端删除加二次确认；后端按 document_id 删除 metadata 和 vector chunks。

---

## Deferred Work

- 多用户隔离和登录鉴权。
- 后台任务队列、上传进度流式推送。
- OCR、表格解析、Office 文档解析。
- BGE-M3 sparse / ColBERT 多路召回。
- PostgreSQL full-text search + pgvector 的混合检索。
- 文档版本管理和增量重建。

---

## References

- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3
- LangChain text splitters: https://docs.langchain.com/oss/python/integrations/splitters
- LangChain Hugging Face embeddings: https://docs.langchain.com/oss/python/integrations/text_embedding/huggingfacehub
- LangChain PGVector: https://docs.langchain.com/oss/python/integrations/vectorstores/pgvector
- pgvector: https://github.com/pgvector/pgvector
