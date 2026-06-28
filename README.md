# Shane's Site

这是一个本地三服务个人站点：

- `apps/frontend`: Vue 3 + Vite + UnoCSS 个人站点前端，包含左侧侧边栏、首页和 AI 问答页。
- `services/java-api`: Spring Boot Java API，默认端口 `8080`。
- `services/python-api`: FastAPI Python API，默认端口 `8000`。

前端默认运行在 `http://127.0.0.1:5173`，并通过 Vite dev proxy 转发：

- `/java-api/*` -> `http://127.0.0.1:8080/*`
- `/python-api/*` -> `http://127.0.0.1:8000/*`

## 依赖安装

macOS Intel 环境优先使用 Homebrew：

```bash
brew install node pnpm
brew install --cask temurin
brew install uv
```

如果你已经安装了 Oracle JDK 17+ 或 SDKMAN 管理的 JDK，可以继续使用已有 JDK。当前 Spring Boot 要求 Java 17+，Vite/Vue 当前文档要求 Node `^20.19.0 || >=22.12.0`。

## 版本检查

```bash
node --version
which node
pnpm --version
java -version
uv --version
python3 --version
```

期望结果：

- Node: `20.19.0` 或更高的 `20.x`，或 `22.12.0` 以上，或当前 LTS/Current 版本；`which node` 应指向同一个新版 Node，不应落到旧的 `/usr/local/bin/node`。
- pnpm: 能执行 `pnpm install` 和 `pnpm dev`。
- Java: `17` 或更高。
- uv: 能执行 `uv sync` 和 `uv run`。
- Python: `3.11` 或更高；uv 可按 `.python-version` 管理 Python。

## 启动 Java API

先确认 Maven 使用的是 Java 17+：

```bash
mvn -version
```

输出里的 `Java version` 必须是 `17` 或更高，Maven 建议 `3.6.3` 或更高。如果默认 `java` 指向 Java 8，请先切换到 Java 17+。例如 macOS 可临时设置：

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
mvn -version
```

启动命令里的插件前缀必须是 `spring-boot`，不是 `spring`：

```bash
cd services/java-api
mvn spring-boot:run
```

健康检查：

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/site
```

## 启动 Python API

推荐使用 uv：

```bash
cd services/python-api
uv sync
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000
```

AI 问答使用 LangChain + Anthropic 兼容接口。配置参考本机 `~/.claude/settings.json` 的 `env` 字段，也可以直接用环境变量覆盖：

```bash
export ANTHROPIC_BASE_URL="https://token-plan-cn.xiaomimimo.com/anthropic"
export ANTHROPIC_MODEL="mimo-v2.5-pro"
export ANTHROPIC_AUTH_TOKEN="你的 token"
export AI_THINKING_ENABLED="true"
export AI_THINKING_BUDGET_TOKENS="1024"
export AI_TIMEZONE="Asia/Shanghai"
```

不要把 token 写入 Git。未配置 token 时，`/api/health` 和 `/api/site` 仍可用，`/api/chat` 会返回配置错误。AI 系统提示词会在每次模型调用前注入当前时间，默认时区为 `Asia/Shanghai`，可用 `AI_TIMEZONE` 覆盖。

Web 搜索作为 LangChain Agent tool 接入，由模型根据问题自主决定是否调用。搜索 provider 可选 `tavily`、`brave`、`serper`，任选其一配置即可：

```bash
export WEB_SEARCH_PROVIDER="tavily"
export WEB_SEARCH_MAX_RESULTS="5"
export TAVILY_API_KEY="你的 Tavily key"

# 或：
export WEB_SEARCH_PROVIDER="brave"
export BRAVE_SEARCH_API_KEY="你的 Brave Search key"

# 或：
export WEB_SEARCH_PROVIDER="serper"
export SERPER_API_KEY="你的 Serper key"
```

未配置对应搜索 key 时，普通聊天不受影响；如果 Agent 决定调用搜索工具，交互记录中会显示工具调用失败原因。前端 AI 问答页提供“联网搜索”和“个人文档 RAG”按钮，本轮请求会通过 `web_search_enabled` 和 `rag_enabled` 控制是否向 Agent 注册对应工具。

个人文档 RAG 使用本机 Docker pgvector + 本地 BGE-M3 embedding。原始上传文件写到 `RAG_UPLOAD_DIR`，解析后的完整纯文本写到 `RAG_PARSED_TEXT_DIR`，文档元数据和向量写入 PostgreSQL：

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

首次向量化会下载 `BAAI/bge-m3` 到 Hugging Face 缓存。默认使用 `refs/pr/130` revision 的 safetensors 权重，以兼容 macOS Intel 上无法安装 torch 2.6+ 的环境。上传接口基于 MD5 做本地判重，重复文件会直接返回已有文档；非重复文件上传后先保存元数据，再手动触发解析、切分和向量化。

```bash
curl -X POST http://127.0.0.1:8000/api/documents/upload \
  -F "file=@/path/to/notes.md"

curl http://127.0.0.1:8000/api/documents

curl -X POST http://127.0.0.1:8000/api/documents/{document_id}/process

curl -X POST http://127.0.0.1:8000/api/documents/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"这份文档讲了什么？","top_k":5}'
```

如果当前机器暂时无法安装 uv，可用 Python venv 作为本地 fallback：

```bash
cd services/python-api
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m fastapi dev app/main.py --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/site
```

AI 问答：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好","session_id":null,"web_search_enabled":true,"rag_enabled":true}'
```

FastAPI 文档页面：

```text
http://127.0.0.1:8000/docs
```

## 启动前端

```bash
cd apps/frontend
pnpm install
pnpm dev
```

打开：

```text
http://127.0.0.1:5173
```

页面应显示左侧侧边栏，以及 Java API 和 Python API 两个服务状态卡片。

## 测试

前端：

```bash
cd apps/frontend
pnpm test
pnpm build
```

Java API：

```bash
cd services/java-api
mvn test
```

Python API：

```bash
cd services/python-api
uv run pytest
```

venv fallback：

```bash
cd services/python-api
.venv/bin/python -m pytest
```

## 端口占用处理

默认端口：

- 前端：`5173`
- Java API：`8080`
- Python API：`8000`

如果端口被占用，先停止占用进程，或同步调整对应服务端口和 `apps/frontend/vite.config.js` 的 proxy target。

## 后续扩展

- 增加第二个真实菜单页面时，再引入 Vue Router。
- 本地三服务启动跑通后，如果需要团队 onboarding 或部署，再增加 Docker Compose。
- 当前后端契约开始频繁变更时，再考虑共享 schema 或代码生成。
