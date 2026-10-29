# MerchPilot 代码阅读与注释指南

本文档面向第一次阅读项目代码的开发者，也可作为面试时介绍系统实现的导航页。项目中的注释重点解释“这个模块负责什么、为什么这样设计、关键业务门禁在哪里”，而不是把代码逐字翻译成中文。

## 1. 注释约定

项目采用四层注释：

1. **文件职责**：每个一方源码文件顶部说明所属层、主要输入输出和不负责的边界。
2. **类型与函数职责**：复杂类型、服务函数和组件说明调用方、返回值及副作用。
3. **业务规则**：人工审批、租户隔离、幂等、验证门禁、上市门禁等关键判断说明“为什么必须这样做”。
4. **复杂状态流**：异步任务、WebSocket、分页检索、跨模块定位和 Agent Mesh 等流程在关键步骤前说明状态变化。

不建议为明显的赋值、循环、样式属性和框架固定写法逐行写注释。此类注释很快会与代码脱节，反而降低可读性。

## 2. 从哪里开始读

推荐按以下顺序理解系统：

1. `README.md`：启动方式、技术栈和已实现能力。
2. `docs/architecture.md`：系统边界、服务关系和部署形态。
3. `backend/src/merchpilot/main.py`：FastAPI 应用生命周期和外部依赖初始化。
4. `backend/src/merchpilot/api/router.py`：所有业务 API 的总入口。
5. `frontend/src/components/dashboard-shell.tsx`：模块级页面切换、URL 恢复、跨模块事件补发和目标面板定位。当前只挂载正在使用的模块，避免历史模块隐藏占用资源。
6. `backend/src/merchpilot/agents/mesh/graph.py`：规划 Mesh 包含 5 个 LLM Agent、7 个确定性业务工具与 1 个人工审批门禁；导入流水线另有 1 个 Qwen-VL 多模态 LLM Agent，统一目录见 `backend/src/merchpilot/agents/catalog.py`。目录共登记 14 个节点，规划图实际执行其中 13 个。
7. `docs/agent-node-topologies.md`：每个规划节点和导入多模态节点的独立流程拓扑、输入输出、边界和源码对照。
8. `backend/src/merchpilot/workers/tasks.py`：Celery 如何真正执行 Agent、导入、索引和报告任务。
9. `backend/src/merchpilot/services/project_lifecycle.py`：同一项目从规划到上市的闭环状态推导。
10. `backend/src/merchpilot/mcp/server.py`：FastMCP 如何以角色权限暴露受控工具。
11. `backend/src/merchpilot/services/demo_workspace.py`：如何用真实实体幂等准备四条可演示业务主线。

## 3. 后端目录地图

| 目录 | 作用 | 阅读重点 |
| --- | --- | --- |
| `adapters/` | 本地身份、对象存储、审批和监控的适配器 | 未来替换阿里云、企业 SSO、OA 时保持业务层不变 |
| `agents/mesh/` | LangGraph Multi-Agent Mesh | 节点并行、重试、恢复和人工审批边界 |
| `api/routes/` | REST/WebSocket 接口 | 参数校验、租户隔离、分页和权限门禁 |
| `core/` | 配置、日志和 ID | 环境变量如何进入系统 |
| `domain/` | 业务枚举 | 状态值的统一定义 |
| `infrastructure/` | PostgreSQL、Redis、Milvus、Celery 和模型客户端 | 连接、持久化与外部服务边界 |
| `llm/` | 大模型网关 | 真实模型与降级行为 |
| `mcp/` | FastMCP 服务、鉴权和 API 客户端 | 工具权限、确认词和幂等写入 |
| `ports/` | 企业能力抽象接口 | 本地实现与未来企业实现之间的契约 |
| `services/` | 可复用业务规则 | 财务、供应商、检索治理、门禁和闭环推导 |
| `workers/` | Celery 异步任务 | 长任务执行、状态回写和失败恢复 |

## 4. 前端目录地图

| 目录 | 作用 | 阅读重点 |
| --- | --- | --- |
| `app/` | Next.js 页面入口和全局样式 | 应用外壳、主题和响应式布局 |
| `components/` | 面向用户的业务工作台 | 每个业务模块独立分页、筛选和详情交互 |
| `lib/http/` | Axios API 客户端 | 类型契约、查询参数和错误格式 |
| `lib/ws/` | WebSocket 客户端 | Agent 实时进度与断线恢复 |
| `store/` | Redux Toolkit 状态 | 身份、当前运行、跨模块当前项目和持久化快照 |

跨模块连续操作建议按以下顺序阅读：

1. `frontend/src/components/demo-workspace-panel.tsx`：首次使用入口、四场景导航、Milvus 索引进度和安全重试。
2. `frontend/src/store/project-context-slice.ts`：当前项目的 Redux 状态、恢复、切换和清除语义。
3. `frontend/src/components/project-context-bar.tsx`：远程项目检索、本地持久化、网址深链、失效项目恢复、项目信息补全、八阶段闭环进度、角色化下一步和四个主流程入口。
4. `frontend/src/components/dashboard-shell.tsx`：模块级页面切换、URL 恢复、跨模块事件补发和目标面板定位。当前只挂载正在使用的模块，避免历史模块隐藏占用资源。
5. `planning-workspace.tsx`、`approval-panel.tsx`、`selected-product-panel.tsx`、`product-initiative-panel.tsx`：各模块如何接收当前项目、重置局部筛选，并在打开业务记录时反向同步项目。
6. 后端 `demo_workspace.py`、`analytics.py`、`approvals.py`、`selected_products.py` 和 `product_initiatives.py`：演示实体如何生成，以及项目条件如何约束闭环推导、分页列表和汇总统计。

## 5. 核心业务闭环

```mermaid
flowchart LR
    A["数据导入与质量治理"] --> B["商品规划项目"]
    B --> C["Agent Mesh 分析"]
    C --> D["人工规划审批"]
    D --> E["正式选品与验证"]
    E --> F["商品立项与里程碑"]
    F --> G["人工上市评审"]
    G --> H["上市确认与经营复盘"]
```

任何自动化入口都不能绕过人工审批和验证门禁。REST、页面和 FastMCP 使用同一套后端规则，避免不同入口产生不一致结果。

## 6. Agent Mesh 节点分层

`backend/src/merchpilot/agents/mesh/graph.py` 注册 13 个规划节点；`backend/src/merchpilot/agents/catalog.py` 另外登记导入流水线的多模态证据 Agent。

### 6.1 规划 LLM Agent（5 个）

1. 需求理解
2. 研究规划
3. 商品概念
4. 方案审查
5. 规划报告

这些节点有独立 Prompt、Pydantic 输出契约、模型元数据和确定性降级策略。

### 6.2 确定性业务工具（7 个）

1. 市场研究检索
2. 竞品研究检索
3. 用户洞察检索
4. 证据治理与补充检索
5. 供应商评估
6. 财务测算
7. 机会评分

这些节点不由模型自由编造结果，关键数值和证据状态由规则、PostgreSQL、Milvus 或检索服务计算。

最后的 `review_agent` 是人工审批门禁适配节点，只把运行状态切换为“需要审批”，不会替代审批人自动作出业务决策。完整元数据可以通过 `/api/v1/agents/catalog` 查询。

### 6.3 导入流水线多模态 LLM Agent（1 个）

`multimodal_evidence_agent` 使用 `qwen-vl-max` 处理 PDF、PPTX、DOCX 和图片，执行 OCR、表格/图表识别和结构化证据抽取；Qwen-VL 不可用时只保留文档原生文本，并标记 `warning`、`needs_review=true`，不会伪造图片事实。

## 7. 数据与基础设施

- **PostgreSQL**：业务事实、审批记录、运行状态、审计和幂等账本。
- **Redis**：Celery Broker、结果通道、缓存和实时状态。
- **Milvus**：证据向量索引和语义检索。
- **Celery**：数据导入、向量索引、Agent 分析和报告生成等长任务。
- **Docker Compose**：本地完整运行环境。
- **FastMCP**：把已有业务 API 转换为受身份、角色和确认门禁约束的工具。

## 8. 如何继续维护注释

- 新增文件时必须先写文件职责。
- 新增业务状态时，同时更新枚举、Schema、页面展示和测试说明。
- 涉及审批、归档、幂等、租户和数据可见性的代码必须解释设计原因。
- 代码行为变化时同步修改附近注释；过期注释按缺陷处理。
- 可运行 `make comments` 检查一方源码是否缺少文件职责说明。

## 9. 不直接添加注释的文件

以下文件由工具生成或格式本身不支持注释，不在文件内部强行写入说明：

- `package.json`、`pnpm-lock.yaml` 等标准 JSON/锁文件。
- `next-env.d.ts`、`.next/`、`node_modules/`、Python 虚拟环境和缓存。
- 数据采集结果、上传文件、数据库文件和渲染产物。

它们的用途统一在本文档和相邻配置文件中说明。

## 10. 历史辅助脚本

`.workbook/` 保存此前用于律师信息工作簿整理、采集和渲染验收的独立脚本。它们已经补充文件与函数说明，但**不属于 MerchPilot 的运行、构建或业务闭环**；阅读商品规划系统时可以跳过该目录。

## 11. 面试学习与个人分工

如果只需要负责部分开发，不必平均阅读所有页面和接口。建议优先深挖“证据检索 → Multi-Agent Mesh → Celery → Redis Checkpoint → 人工审批恢复”主链路，再用项目生命周期模块理解规划、选品、验证、立项和上市评审如何连接。

详细的必学范围、可主责范围、面试表述边界和阅读顺序见 [`docs/interview-development-scope.md`](interview-development-scope.md)。
