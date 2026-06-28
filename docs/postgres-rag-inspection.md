# PostgreSQL / pgvector 查看说明

## 1. 数据库连接信息

当前项目的个人文档 RAG 数据存储在本机 Docker PostgreSQL + pgvector 容器中。

| 配置项 | 值 |
| --- | --- |
| 容器名 | `suprag-postgres-vector` |
| 镜像 | `pgvector/pgvector:pg16` |
| Host | `127.0.0.1` |
| Port | `5432` |
| Database | `suprag_vector` |
| Username | `postgres` |
| Password | `suprag` |

标准 PostgreSQL 连接串：

```text
postgresql://postgres:suprag@127.0.0.1:5432/suprag_vector
```

项目 RAG 配置文件：

```text
services/python-api/.env.local
```

项目使用的 SQLAlchemy / LangChain 连接串格式：

```bash
RAG_PGVECTOR_CONNECTION="postgresql+psycopg://postgres:suprag@127.0.0.1:5432/suprag_vector"
```

`.env.local` 是本机私有配置，不应提交到 Git。

## 2. 命令行查看

进入 PostgreSQL：

```bash
docker exec -it suprag-postgres-vector psql -U postgres -d suprag_vector
```

查看所有表：

```sql
\dt
```

查看表结构：

```sql
\d+ rag_documents
\d+ kb_chunk_embedding
\d+ langchain_pg_collection
\d+ langchain_pg_embedding
```

## 3. RAG 相关表

### `rag_documents`

项目自己维护的文档元数据表。

| 字段 | 说明 |
| --- | --- |
| `id` | 文档 ID |
| `filename` | 原始文件名 |
| `content_type` | 文件类型 |
| `size_bytes` | 文件大小 |
| `md5` | 文件 MD5，用于判重 |
| `original_path` | 原始上传文件本地路径 |
| `parsed_text_path` | 解析后的完整纯文本路径 |
| `status` | 摄取进度：`uploaded` / `parsing` / `parsed` / `chunking` / `chunked` / `vectorizing` / `ready` |
| `chunk_count` | 已写入向量库的 chunk 数 |
| `is_failed` | 当前进度是否失败，失败时 `status` 保留在失败阶段 |
| `error_message` | 失败原因 |
| `failed_at` | 最近一次失败时间 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

查询文档列表：

```sql
select
  id,
  filename,
  status,
  is_failed,
  chunk_count,
  original_path,
  parsed_text_path,
  error_message,
  created_at,
  updated_at
from rag_documents
order by created_at desc;
```

### `langchain_pg_collection`

LangChain PGVector 创建的 collection 表。

```sql
select * from langchain_pg_collection;
```

如果该表不存在，通常表示向量写入还未开始或尚未成功完成。

### `langchain_pg_embedding`

LangChain PGVector 创建的向量数据表。

查看 chunk 数量：

```sql
select count(*) from langchain_pg_embedding;
```

查看 chunk 内容和元数据：

```sql
select
  id,
  collection_id,
  document,
  cmetadata
from langchain_pg_embedding
limit 10;
```

`embedding` 字段是向量数组，长度较大，日常排查不建议直接全量查询。

### `kb_chunk_embedding`

当前库里已有的另一张 pgvector 表，不是本次个人文档 RAG 首版主要写入表。

查看数量：

```sql
select count(*) from kb_chunk_embedding;
```

查看结构：

```sql
\d+ kb_chunk_embedding
```

## 4. 可视化工具连接

可以使用 DBeaver、DataGrip、TablePlus 等 PostgreSQL 客户端连接。

| 配置项 | 值 |
| --- | --- |
| 类型 | PostgreSQL |
| Host | `127.0.0.1` |
| Port | `5432` |
| Database | `suprag_vector` |
| User | `postgres` |
| Password | `suprag` |

连接后重点查看：

```text
rag_documents
langchain_pg_collection
langchain_pg_embedding
kb_chunk_embedding
```

## 5. 本地文件位置

原始上传文件：

```text
services/python-api/data/uploads/
```

解析后的完整纯文本：

```text
services/python-api/data/parsed/
```

PostgreSQL 中保存文档元数据、文件路径、chunk 内容和向量；完整解析纯文本保存在本地文件系统。

## 6. 常用排查 SQL

查看当前文档状态：

```sql
select
  id,
  filename,
  status,
  is_failed,
  chunk_count,
  parsed_text_path,
  failed_at,
  error_message
from rag_documents
order by created_at desc;
```

查看处理中记录：

```sql
select id, filename, status, chunk_count, error_message
from rag_documents
where status in ('parsing', 'parsed', 'chunking', 'chunked', 'vectorizing')
  and is_failed = false;
```

查看失败记录：

```sql
select id, filename, status, error_message, failed_at, updated_at
from rag_documents
where is_failed = true
order by failed_at desc;
```

查看已完成记录：

```sql
select id, filename, chunk_count, parsed_text_path, updated_at
from rag_documents
where status = 'ready'
order by updated_at desc;
```

查看当前数据库连接和长查询：

```sql
select
  pid,
  state,
  wait_event_type,
  wait_event,
  now() - query_start as age,
  left(query, 160) as query
from pg_stat_activity
where datname = current_database()
order by query_start nulls last;
```

## 7. 一条命令快速查看

```bash
docker exec -it suprag-postgres-vector psql -U postgres -d suprag_vector -c \
"select id, filename, status, chunk_count, parsed_text_path, error_message from rag_documents order by created_at desc;"
```
