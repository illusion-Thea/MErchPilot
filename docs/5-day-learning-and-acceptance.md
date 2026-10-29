# MerchPilot 五天系统学习与验收手册

> 适用日期：2026 年 9 月 4 日
>
> 学习目标：五天内建立对 MerchPilot 的整体架构理解，并能够独立讲清楚一条“数据治理 → Multi-Agent → 异步执行 → 人工审批 → 正式选品 → 商品立项 → 上市评审”的核心链路。

## 一、学习方式

这五天不追求逐文件读完，而采用“先建立系统地图，再深挖一个核心方向，最后用运行结果验收”的方式。

每天固定完成四类产出：

1. **阅读产出**：记录当天读过的文件和每个文件的职责。
2. **运行产出**：至少完成一次接口、页面或测试验证。
3. **表达产出**：用自己的话画图或解释一条数据流。
4. **验收产出**：回答当天问题；没有通过就先补缺口，不直接进入下一天。

推荐个人主责方向：

> 证据检索 → LangGraph Multi-Agent Mesh → Celery → Redis Checkpoint → WebSocket → 人工审批恢复。

其他模块需要理解边界和状态流，不要求第一轮逐行掌握所有页面、样式、适配器和运维脚本。

## 二、五天总览

| 天数 | 学习主题 | 必须掌握的结果 | 当天主要代码范围 |
| --- | --- | --- | --- |
| 第 1 天 | 全局架构与运行环境 | 能画出服务拓扑，说明每个基础设施的职责 | `README.md`、`docs/architecture.md`、`backend/src/merchpilot/main.py`、`backend/src/merchpilot/api/router.py`、`docker-compose.yml` |
| 第 2 天 | 数据治理与 RAG 检索 | 能说明表格、PDF、PPT、DOCX 和图片如何变成可追溯证据，以及 PostgreSQL/Milvus 如何协作 | `services/tabular_import.py`、`services/multimodal_import.py`、`services/data_import.py`、`agents/prompts.py`、`services/retrieval.py`、`services/retrieval_governance.py`、`infrastructure/milvus.py`、`workers/tasks.py` |
| 第 3 天 | Agent Mesh 与异步执行 | 能讲清 5 个 LLM Agent、7 个确定性工具、并行节点、重试、Checkpoint、WebSocket 和恢复 | `agents/catalog.py`、`agents/mesh/graph.py`、`workers/tasks.py`、`infrastructure/checkpoints.py`、`api/routes/websocket.py`、`frontend/src/lib/ws/run-socket.ts`、`frontend/src/store/run-slice.ts` |
| 第 4 天 | 业务闭环与用户页面 | 能从用户视角走完规划、审批、选品、验证、立项和上市评审 | `services/project_lifecycle.py`、`api/routes/approvals.py`、`api/routes/selected_products.py`、`api/routes/product_initiatives.py`、前端四个业务面板 |
| 第 5 天 | FastMCP、企业化与面试验收 | 能解释 MCP 权限边界，并完成一次完整演示和面试表达 | `mcp/server.py`、`mcp/auth.py`、`mcp/api_client.py`、`adapters/`、`docker-compose.yml`、`scripts/validate-local.sh` |

## 三、第 1 天：全局架构与运行环境

### 3.1 学习目标

今天结束时必须能够回答：

- 用户从前端发起一次规划后，请求经过哪些服务？
- 为什么同时使用 PostgreSQL、Redis 和 Milvus？
- 哪些事情在 API 进程内完成，哪些事情交给 Celery Worker？
- 哪些能力是当前本地实现，哪些能力只是为企业环境预留？

### 3.2 阅读顺序

按下面顺序阅读，不要一开始钻进某个 Agent 的提示词：

1. `README.md`：只看“当前阶段”“本地启动”“运行与审批规则”“数据职责”。
2. `docs/architecture.md`：重点看 Runtime topology、Architecture boundaries 和 Reliability rules。
3. `docker-compose.yml`：只整理服务名、端口、依赖和持久化卷。
4. `backend/src/merchpilot/main.py`：看 FastAPI 生命周期、Provider 初始化和路由挂载。
5. `backend/src/merchpilot/api/router.py`：看业务路由分组，不需要逐条阅读接口实现。
6. `frontend/src/app/page.tsx`、`frontend/src/components/dashboard-shell.tsx`：看页面入口、身份门禁、模块导航和 URL 恢复。
7. `frontend/src/store/index.ts`、`frontend/src/store/identity-slice.ts`、`frontend/src/store/project-context-slice.ts`：看前端全局状态边界。

### 3.3 运行任务

先检查本地服务，不要重复构建已经正常运行的环境：

```bash
docker compose ps
```

如果服务未启动，再使用项目统一入口：

```bash
make dev
```

另开终端验证入口：

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl -I http://localhost:3001/
```

如果当前机器没有启动 Docker，不要停在环境问题上；先完成代码阅读，并记录“运行态验证待补”。

### 3.4 当天必须提交的产出

请自己写一页，不要复制文档：

1. 画一张服务拓扑图，至少包含 Web、API、Worker、FastMCP、PostgreSQL、Redis、Milvus、Embedding 和 Reranker。
2. 写一张职责表：PostgreSQL、Redis、Milvus、Celery 各保存或处理什么，明确它们不负责什么。
3. 用 5～8 句话描述“点击启动规划”后的请求链路。
4. 标出你准备在第 2～3 天深挖的 8 个文件。

### 3.5 第 1 天验收题

完成后直接回复答案，我会按题号批改：

1. 为什么不能让 Milvus 作为项目、审批和选品的唯一数据库？
2. Redis 发生短暂不可用时，哪些数据必须仍然能够从 PostgreSQL 恢复？
3. 为什么规划分析不应该由 FastAPI 请求线程同步执行？
4. `main.py`、`api/router.py` 和 `workers/tasks.py` 分别处于哪一层，职责边界是什么？
5. 当前本地身份和未来企业 SSO 的替换点在哪里？
6. 画出“浏览器 → API → Celery → Agent → PostgreSQL/Redis → WebSocket”的时序简图。

### 3.6 通过标准

满分 10 分，达到 7 分进入第 2 天：

- 服务拓扑和职责表：3 分。
- 请求链路解释准确：3 分。
- 能区分事实数据、临时状态和向量索引：2 分。
- 能指出本地实现与企业预留边界：1 分。
- 能说明一个可靠性设计原因：1 分。

## 四、第 2 天：数据治理与 RAG 检索

### 学习目标

把一份 Excel/CSV 从上传、解析、列名归一化、质量校验、PostgreSQL 台账、Embedding、Milvus 索引到检索召回完整串起来。

### 阅读任务

- 先读 `backend/src/merchpilot/services/tabular_import.py`，理解表格解析和字段标准化。
- 再读 `backend/src/merchpilot/services/data_import.py`，理解导入任务状态和来源追踪。
- 再读 `backend/src/merchpilot/services/retrieval.py` 与 `retrieval_governance.py`，重点看租户、质量和来源过滤。
- 最后看 `backend/src/merchpilot/infrastructure/milvus.py`、`backend/src/merchpilot/infrastructure/postgres.py` 和相关导入 Worker。

### 运行任务

- 在“数据治理”模块查看导入记录、质量问题和重复候选。
- 使用检索工作台查询一个关键词，记录返回的证据、来源和质量状态。
- 找到一条证据在 PostgreSQL 中的元数据，以及它在 Milvus 中用于检索的字段。

### 验收重点

能够解释：为什么“Milvus 召回证据后还要回 PostgreSQL 二次确认”；导入失败、向量索引失败和证据撤回分别如何处理；为什么不能让模型直接自由拼接未经治理的数据。

## 五、第 3 天：Agent Mesh 与异步执行

### 学习目标

重点深挖个人主责方向：5 个 LLM Agent、7 个确定性工具、并行依赖、节点级重试、运行快照、人工审批等待和恢复执行。

### 阅读任务

- `backend/src/merchpilot/agents/mesh/graph.py`：先看 `MeshState`、节点注册和边关系，再看单个 Agent 实现。
- `backend/src/merchpilot/workers/tasks.py`：重点看规划任务、状态回写、事件发布、恢复和 Celery 入口。
- `backend/src/merchpilot/infrastructure/checkpoints.py`：理解 Redis Checkpoint 与 PostgreSQL 快照的关系。
- `backend/src/merchpilot/api/routes/websocket.py`、`frontend/src/lib/ws/run-socket.ts`：理解增量事件和刷新恢复。
- `frontend/src/store/run-slice.ts`、`frontend/src/components/planning-workspace.tsx`：理解用户看到的进度如何映射到后端状态。

### 运行任务

- 创建或选择一个规划项目并启动运行。
- 记录 13 个节点的执行顺序，找出两组可以并行的节点，并说明哪些节点必须使用确定性规则而不是模型生成。
- 在运行过程中刷新页面，观察哪些状态从快照恢复，哪些事件只来自实时流。
- 找到一次失败或重试记录，解释为什么是节点级重试而不是整条流程重跑。

### 验收重点

能够画出 Agent Mesh 图，并说明 `review_agent` 为什么只是人工审批门禁；能够解释 Celery、Redis、PostgreSQL、WebSocket 各自的职责；能够说明审批后如何从保存状态恢复，而不是重复调用已完成节点。

## 六、第 4 天：业务闭环与用户页面

### 学习目标

从用户角度走通：规划项目 → Agent 运行 → 线上审批 → 正式选品 → 验证门禁 → 商品立项 → 试销/上市评审。

### 阅读任务

- `backend/src/merchpilot/services/project_lifecycle.py`：理解项目级状态推导和下一步动作。
- `backend/src/merchpilot/services/validation_guard.py`、`launch_review_guard.py`：理解两个关键门禁。
- `backend/src/merchpilot/api/routes/approvals.py`、`selected_products.py`、`product_initiatives.py`：理解状态变更和权限校验。
- `frontend/src/components/dashboard-shell.tsx`：理解按模块切换和当前项目上下文。
- `frontend/src/components/planning-workspace.tsx`、`approval-panel.tsx`、`selected-product-panel.tsx`、`product-initiative-panel.tsx`：理解列表分页、详情和跨模块跳转。

### 运行任务

至少用两个本地身份体验系统：`planner` 和 `approver`。观察不同角色看到的模块和可操作按钮差异，并完成一次审批后的自动进入下一业务模块。

### 验收重点

能够解释为什么审批通过才能生成正式选品；为什么验证门禁必须有人工材料；为什么上市评审不能由 Agent 自动批准；为什么页面按模块分页且列表采用服务端分页。

## 七、第 5 天：FastMCP、企业化与面试验收

### 学习目标

把当前系统从“能运行”提升到“能讲清楚、能落地、能面试”：理解 FastMCP 是适配层，不复制业务规则；理解 Docker、Provider、权限、幂等和审计的企业边界。

### 阅读任务

- `backend/src/merchpilot/mcp/server.py`：工具、角色、确认词、幂等和只读/写入边界。
- `backend/src/merchpilot/mcp/auth.py`、`api_client.py`：协议身份如何转为既有 API 调用。
- `docs/fastmcp-integration.md`：工具目录和安全约束。
- `backend/src/merchpilot/adapters/`、`ports/`：本地实现与未来 OSS、SSO、OA、监控平台的替换点。
- `scripts/validate-local.sh`：完整业务闭环验收脚本。

### 运行任务

服务正常时执行：

```bash
make validate-local
```

重点观察 FastMCP 的工具清单、viewer/planner/approver 的工具差异、确认词、幂等返回和人工审批边界。

### 最终验收

完成以下 5 项：

1. 用 3 分钟讲清系统架构和业务价值。
2. 用 5 分钟讲清一次规划运行的时序和异常恢复。
3. 现场回答“为什么 PostgreSQL + Milvus”“为什么 Redis + Celery”“为什么需要人在环”。
4. 指出你个人最适合负责的模块、一个真实技术难点和一个后续改进点。
5. 任选一个核心函数，说明输入、输出、副作用、错误处理和测试覆盖。

## 八、每日回复格式

每天学习结束后按下面格式回复，我会按验收标准批改，不只给鼓励：

```text
第 N 天学习记录

1. 今日阅读文件：
2. 我理解的主流程：
3. 今日运行结果：
4. 我画出的数据流/状态流：
5. 验收题答案：
6. 仍然不理解的地方：
```

## 九、最终能力标准

五天结束不要求你成为所有模块的维护者，但应该达到以下水平：

- 能从用户动作讲到 API、业务服务、任务队列、Agent、数据库和前端反馈。
- 能深挖证据检索、Agent 编排、Celery/Redis 状态恢复中的至少一个方向。
- 能解释审批、验证、上市评审为什么必须保留人工决策。
- 能看懂服务端分页、租户隔离、幂等、审计和 Provider 扩展点。
- 能诚实区分“自己重点负责”“团队协作完成”和“未来预留”。

这套标准足以支撑项目学习、核心模块开发和面试技术追问。
