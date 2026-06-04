# CLAUDE.md

## 项目概述

这是一个智能对话智能体项目，目标是用 FastAPI 提供后端 API，用 LangChain 编排对话与 RAG 流程，核心 LLM 与 embedding 服务使用阿里千问 / DashScope，向量数据库使用 Chroma。

## 当前初始化文件

- `app/main.py`：FastAPI 应用入口，提供首页、聊天占位接口和知识库上传接口，并在 lifespan 中初始化 SQLite MD5 索引服务。
- `app/templates/index.html`：模板分离的首页，包含聊天框和 RAG 知识库上传模块。
- `app/static/app.css`：首页样式。
- `app/static/app.js`：首页聊天和上传交互。
- `tests/test_app.py`：FastAPI 行为测试。
- `requirements.txt`：Python 依赖清单。
- `.gitignore`：忽略虚拟环境、缓存、密钥、本地向量库和临时文件。
- `README.md`：给开发者看的项目说明。
- `CLAUDE.md`：给 Claude Code 看的项目上下文和开发约定。

## 开发约定

- 使用中文与用户沟通，代码命名优先保持英文语义清晰。
- 不要把 API Key、`.env`、本地向量库数据、上传文件或日志提交进项目。
- 阿里千问相关凭据从环境变量读取，默认变量名使用 `DASHSCOPE_API_KEY`。
- Chroma 本地持久化目录默认使用 `./data/chroma`，该目录应保持 git 忽略。
- 后续新增 Python 依赖时，同步更新 `requirements.txt`。
- 当前项目 Python 命令使用 Conda 环境 `agent`，在 Claude 的 Git Bash 环境中用 `cmd.exe //C "D:\Anaconda\Scripts\activate && conda activate agent && <command>"` 执行。
- 优先保持模块职责单一：API 路由、模型封装、向量库、知识库处理、RAG 流程分开维护。
- 应用级共享资源放在 `app.state`；当前 SQLite 连接为 `app.state.sqlite`，知识库服务为 `app.state.knowledge_base`，服务层不要反向导入 FastAPI app。
- Chroma 是 RAG 使用的向量数据库；SQLite 只用于存储已处理文本的 MD5 索引和快速去重，不保存正文内容。
- 对低风险、可逆的本地文件操作可直接执行；涉及删除、覆盖用户改动、联网发布、推送代码、修改共享资源等高风险操作前仍需确认。

## 推荐后续模块边界

- API 层：FastAPI 路由、请求响应模型、文件上传入口。
- LLM 层：千问聊天模型与 embedding 模型初始化。
- 向量库层：Chroma collection 创建、持久化和检索。
- 知识库层：文档解析、切分、入库。
- RAG 层：检索上下文组装、提示词、对话链调用。
