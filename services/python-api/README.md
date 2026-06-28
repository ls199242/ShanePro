# Personal Site Python API

FastAPI service for the personal site.

## AI Chat

`POST /api/chat` uses a LangChain agent with an Anthropic-compatible Mimo endpoint.

Configuration is read from environment variables first, then `services/python-api/.env.local`,
then `services/python-api/.env`, then `~/.claude/settings.json` `env`:

```bash
export ANTHROPIC_BASE_URL="https://token-plan-cn.xiaomimimo.com/anthropic"
export ANTHROPIC_MODEL="mimo-v2.5-pro"
export ANTHROPIC_AUTH_TOKEN="your token"
export AI_THINKING_ENABLED="true"
export AI_THINKING_BUDGET_TOKENS="1024"
export AI_TIMEZONE="Asia/Shanghai"
```

The system prompt injects the current time before each model call. `AI_TIMEZONE` defaults to `Asia/Shanghai`.

Web search tool:

```bash
export WEB_SEARCH_PROVIDER="tavily"
export WEB_SEARCH_MAX_RESULTS="5"
export TAVILY_API_KEY="your Tavily key"

# Or use Brave Search:
export WEB_SEARCH_PROVIDER="brave"
export BRAVE_SEARCH_API_KEY="your Brave Search key"

# Or use Serper:
export WEB_SEARCH_PROVIDER="serper"
export SERPER_API_KEY="your Serper key"
```

The LangChain agent decides when to call the web search tool. Set `web_search_enabled` to `false` on a chat request to run that turn without registering the search tool. Search failures are returned as tool results so the chat request can continue.

## Personal Document RAG

Document RAG stores uploaded originals and parsed text locally, while metadata and vectors live in PostgreSQL with pgvector.

Configuration:

```bash
export RAG_PGVECTOR_CONNECTION="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"
export RAG_PGVECTOR_COLLECTION="personal_documents_bge_m3"
export RAG_EMBEDDING_MODEL="BAAI/bge-m3"
export RAG_EMBEDDING_REVISION="refs/pr/130"
export RAG_EMBEDDING_DEVICE="cpu"
export RAG_CHUNK_SIZE="1000"
export RAG_CHUNK_OVERLAP="150"
export RAG_RETRIEVAL_TOP_K="5"
export RAG_UPLOAD_DIR="data/uploads"
export RAG_PARSED_TEXT_DIR="data/parsed"
```

For local development, put machine-specific database credentials in `services/python-api/.env.local`.
That file is ignored by Git.

Upload a document:

```bash
curl -X POST http://127.0.0.1:8000/api/documents/upload \
  -F "file=@/path/to/notes.md"
```

List documents:

```bash
curl http://127.0.0.1:8000/api/documents
```

Process a document:

```bash
curl -X POST http://127.0.0.1:8000/api/documents/{document_id}/process
```

Search documents:

```bash
curl -X POST http://127.0.0.1:8000/api/documents/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"这份文档讲了什么？","top_k":5}'
```

The first vectorization may download `BAAI/bge-m3` into the Hugging Face cache. By default the service uses the `refs/pr/130` safetensors revision so macOS Intel can keep using the available torch wheel without triggering `torch.load`. The upload API uses MD5 for local duplicate detection. Parsed full text is written to `RAG_PARSED_TEXT_DIR/{document_id}.txt`, and chunk text plus vectors are written to pgvector.

Request:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好","session_id":null,"web_search_enabled":true,"rag_enabled":true}'
```

The service keeps chat history in memory by `session_id`. Restarting the Python process clears the history.
