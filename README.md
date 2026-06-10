# 智能对话智能体

这是一个基于 FastAPI、LangChain、DashScope、Chroma 和 SQLite 的智能对话智能体项目。Web 聊天入口会先检索 FAQ，高置信命中时直接返回标准答案，否则回退到带工具调用能力的 LangChain Agent；同时提供 RAG 文档知识库、FAQ 管理、会话历史和企业微信回调接入能力。

## 核心能力

- **Web 聊天**：`/` 提供聊天页面，`POST /api/chat` 支持 NDJSON 流式回复和普通 JSON 回复。
- **FAQ 优先路由**：聊天请求先走 FAQ 检索，命中后直接返回 FAQ 答案；低分或检索失败时回退到 Agent。
- **FAQ 管理**：支持标准问、答案、分类、标签、优先级、状态和扩展问维护，并同步写入 SQLite FTS5 与 Chroma 向量索引。
- **RAG 文档知识库**：支持上传 UTF-8 文本文档，切分 chunk 后写入 Chroma；SQLite 保存 document/chunk 哈希索引、归属关系、状态和统计信息。
- **Agent 工具调用**：普通 Agent 使用千问模型，内置当前时间、本地知识库检索和 Tavily 联网搜索工具。
- **会话与记忆**：LangGraph checkpoint、会话统计、聊天消息和平台入站消息都持久化到 SQLite。
- **企业微信接入**：提供企业微信 URL 验证、明文回调消息处理、异步回复和主动发送文本消息接口。
- **管理页面**：`/admin/rag` 用于文档知识库调试，`/admin/faq` 用于 FAQ 维护和检索测试。

## 技术栈

- 后端 API：FastAPI
- ASGI 服务：Uvicorn
- LLM / Agent 编排：LangChain、LangGraph checkpoint
- 大模型与 embedding：阿里千问 / DashScope
- 向量数据库：Chroma
- 结构化存储：SQLite
- FAQ 关键词检索：SQLite FTS5
- 文档处理：LangChain text splitters、pypdf
- 联网搜索：Tavily
- 配置管理：python-dotenv、PyYAML、pydantic-settings
- 前端页面：Jinja2 模板 + 原生 JavaScript

## 项目结构

```text
.
├── app/
│   ├── api/                    # FastAPI 路由：聊天、RAG、FAQ、平台接入、页面
│   ├── core/                   # 配置与依赖获取
│   ├── schemas/                # 请求 / 响应模型
│   ├── services/               # 聊天编排、运行时、会话历史、企业微信服务
│   ├── static/                 # 前端样式与脚本
│   ├── templates/              # 聊天页、RAG 管理页、FAQ 管理页
│   └── main.py                 # FastAPI 应用入口与 lifespan 初始化
├── agent/
│   ├── rag/                    # RAG 知识库、切分、检索管线、RagService
│   ├── utils/                  # 配置、日志、文件和路径工具
│   ├── bot.py                  # LangChain AgentService
│   ├── checkpointer.py         # SQLite LangGraph checkpoint
│   ├── middleware.py           # Agent / 模型调用中间件
│   ├── prompts/                # Agent 系统提示词
│   └── tools.py                # Agent 工具：时间、知识库检索、联网搜索
├── faq/
│   └── service.py              # FAQ CRUD、FTS5 + Chroma 双路检索
├── configs/
│   ├── agent_config.yml        # Agent 模型、工具、上下文与流式配置
│   ├── rag_config.yml          # RAG、Chroma、SQLite、embedding、切分配置
│   └── prompts_config.yml      # 提示词文件路径配置
├── tests/                      # Pytest 测试
├── requirements.txt            # Python 依赖
└── README.md
```

## 配置

在项目根目录创建 `.env` 文件保存密钥。

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
TAVILY_API_KEY=your_tavily_api_key
```

说明：

- `DASHSCOPE_API_KEY`：千问聊天模型和 embedding 模型必需。
- `TAVILY_API_KEY`：Agent 使用 `search_internet` 联网搜索工具时需要。

公开配置维护在：

- `configs/rag_config.yml`：千问模型、Chroma 持久化目录、SQLite 路径、文档 collection、文本切分和检索默认值。
- `configs/agent_config.yml`：Agent 千问模型、Tavily 参数、上下文阈值和流式输出配置。
- `configs/prompts_config.yml`：提示词文件路径。

当前默认存储位置：

- Chroma：`data/chroma`
- SQLite：`data/sqlite/knowledge_base.sqlite`

`data/`、`.env`、日志、本地向量库和上传文件都应保持 git 忽略。

## 启动服务

在当前 Windows + Conda + Git Bash 环境中启动：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8888"
```

启动后访问：

- 聊天页：`http://127.0.0.1:8888/`
- RAG 管理页：`http://127.0.0.1:8888/admin/rag`
- FAQ 管理页：`http://127.0.0.1:8888/admin/faq`
