# 智能对话智能体

这是一个基于 LangChain、阿里千问、Chroma 和 FastAPI 的智能对话智能体项目初始化模板。

## 技术栈

- 后端 API：FastAPI
- ASGI 服务：Uvicorn
- LLM 编排：LangChain
- 大模型服务：阿里千问 / DashScope
- 向量数据库：Chroma
- 文档处理：pypdf、LangChain text splitters
- 配置管理：python-dotenv、pydantic-settings

## 安装依赖

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

如果在 Linux 或 macOS 环境中使用虚拟环境，激活命令通常是：

```bash
source .venv/bin/activate
```

## 配置

在项目根目录创建 `.env` 文件，只保存不能公开的密钥类参数：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
TAVILY_API_KEY=your_tavily_api_key
```

模型、向量库、数据库、工具参数和提示词等公开配置分别维护在：

- `configs/rag_config.yml`：RAG、Chroma、SQLite、embedding 和文本切分配置。
- `configs/agent_config.yml`：普通 agent 和工具配置。
- `configs/prompts_config.yml`：RAG 与普通 agent 的提示词配置。

不要把 `.env` 提交到版本控制。

## 当前项目结构

```text
.
├── app/
│   ├── main.py
│   ├── static/
│   │   ├── app.css
│   │   └── app.js
│   └── templates/
│       └── index.html
├── memory/
│   ├── __init__.py
│   ├── app_file_upload.py
│   ├── knowledge_base.py
│   ├── rag.py
│   └── vector_stores.py
├── tests/
│   └── test_app.py
├── .gitignore
├── CLAUDE.md
├── README.md
└── requirements.txt
```

## 后续开发方向

1. 在 FastAPI 中提供健康检查、聊天、文件上传和知识库检索接口。
2. 使用 LangChain 封装千问聊天模型和 embedding 模型。
3. 使用 Chroma 持久化向量数据。
4. 将上传文档切分、向量化并写入知识库。
5. 基于检索结果构建 RAG 对话链。

## 启动示例

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8888
```

在当前 Windows + Conda 环境中，可以使用：

```bat
D:\Anaconda\Scripts\activate && conda activate agent && uvicorn app.main:app --reload
```

启动后打开浏览器访问 `http://127.0.0.1:8000`。

## 当前接口

- `GET /`：聊天机器人首页。
- `POST /api/chat`：接收消息并返回占位回复。
- `POST /api/knowledge/upload`：接收 UTF-8 文本文档，按 document/chunk 双层模型写入知识库。
- `GET /api/admin/rag/documents`：查看当前 documents 及其 active chunks。
- `GET /api/admin/rag/documents/{document_id}`：查看单个 document 及其 active chunks。
- `DELETE /api/admin/rag/documents/{document_id}`：删除整个 document 及其 active chunks。
- `DELETE /api/admin/rag/documents/{document_id}/chunks/{chunk_id}`：删除某个 document 下的 chunk。
- `POST /api/admin/rag/retrieve`：执行 RAG 检索测试。

## 知识库存储模型

SQLite 保存 document/chunk 的 SHA-256 hash 索引、chunk 归属关系、删除状态和统计信息，不保存原始 document 正文。Chroma 保存 chunk 文本、向量和检索 metadata，并使用 `chk_` 前缀的显式 chunk id。

FastAPI 在应用生命周期启动时创建 `RagService`，默认数据库路径由 `configs/rag_config.yml` 的 `storage.sqlite_path` 配置，当前默认值是 `data/sqlite/knowledge_base.sqlite`。SQLite 连接对象保存在 `app.state.sqlite`，RAG 入口服务保存在 `app.state.rag_service`。

API 层通过 `request.app.state.rag_service` 使用 RAG 能力，不在服务层中反向导入 FastAPI app，避免循环导入。
