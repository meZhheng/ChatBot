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
- `POST /api/knowledge/upload`：接收上传文件，读取 UTF-8 文本内容，用 SQLite 记录文本 MD5，并识别重复文本。

## SQLite MD5 索引

Chroma 负责后续向量存储和 RAG 检索。SQLite 只用于保存已处理文本的 MD5 索引，避免重复处理相同文本，不保存正文内容。

FastAPI 在应用生命周期启动时创建 SQLite 连接，默认数据库路径由 `configs/rag_config.yml` 的 `storage.sqlite_path` 配置，当前默认值是 `data/sqlite/knowledge_base.sqlite`。连接对象保存在 `app.state.sqlite`，知识库服务对象保存在 `app.state.knowledge_base`。

API 层通过 `request.app.state.knowledge_base` 使用服务，不在 `memory/knowledge_base.py` 中反向导入 FastAPI app，避免循环导入。
