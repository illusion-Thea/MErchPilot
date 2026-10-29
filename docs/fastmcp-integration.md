# FastMCP 接入实现与规划

## 目标

在不改变现有 React、FastAPI、Celery、PostgreSQL、Redis 和 Milvus 本地业务闭环的前提下，为企业 Agent、IDE 助手和自动化工作流提供 MCP 能力。MCP 是新的交互适配层，不替代现有 Web 页面、REST API 或内部业务服务。FastMCP 4.0.1 服务已经以独立 Docker 容器落地，通过 `http://localhost:8001/mcp` 提供 11 个只读工具和 6 个受控写入工具，当前工具契约版本为 `0.9.0`；其中 10 个通用只读工具面向全部登录角色，审批任务只读工具仅面向审批角色和管理员。

React 工作台已经增加“Agent 集成”模块：普通业务用户无需理解 JSON-RPC 即可确认 FastMCP 是否运行、当前身份是否通过协议鉴权、能够读取哪个租户、有哪些工具以及每个工具的参数和分页上限。页面可以复制客户端配置，并调用只读经营驾驶舱工具完成真实业务验证；规划人员看到规划受控写入，审批人员看到审批受控写入，管理员看到全部工具和按项目聚合的 Agent 全链路活动。

## 设计原则

1. FastMCP 只负责协议、工具描述和传输，业务规则继续收敛在应用服务中。
2. 所有调用必须携带可验证身份，并映射到现有 `Identity`、租户和角色模型。
3. MCP 工具禁止直接拼接 SQL 或直接操作 Milvus；统一复用租户隔离的数据访问与检索服务。
4. 写操作按风险逐个开放；当前允许创建规划草稿、明确启动 Agent、领取审批任务、明确提交审批决定、单项更新验证门禁和提交上市评审，均复用现有线上业务规则。验证材料仍必须由人工通过 Web 上传，正式选品仍由审批通过后的 Celery 恢复链路生成；上市评审的通过、驳回、修订和最终上市仍由 Web 在线人工处理。
5. FastMCP 依赖使用精确版本锁定，并在升级前通过工具清单快照、契约测试和租户隔离测试。
6. MCP 返回结果默认分页、限制最大页容量，避免把完整证据、审计或历史运行一次写入模型上下文。

## 目录边界

```text
backend/src/merchpilot/mcp/
├── server.py          # 工具注册、角色可见性、输入约束与 HTTP transport
├── auth.py            # Bearer/OIDC 身份校验与 AccessToken 映射
└── api_client.py      # 携带原身份和幂等标识复用 FastAPI 业务接口
```

## 已实现工具

| 工具 | 类型 | 权限 | 说明 |
| --- | --- | --- | --- |
| `list_planning_projects` | 只读 | viewer+ | 分页查询当前租户规划项目 |
| `list_planning_runs` | 只读 | viewer+ | 分页查询指定项目的运行版本 |
| `get_planning_run` | 只读 | viewer+ | 获取运行状态与结果快照 |
| `list_run_evidence` | 只读 | viewer+ | 分页读取引用证据和撤回统计 |
| `search_enterprise_evidence` | 只读 | viewer+ | 复用 BGE-M3、Milvus、Reranker 与治理规则 |
| `list_approval_tasks` | 只读 | approver/admin | 查询本人、未分配或逾期审批 |
| `list_selected_products` | 只读 | viewer+ | 查询正式选品与验证状态 |
| `list_product_initiatives` | 只读 | viewer+ | 分页查询商品立项与推进状态 |
| `get_launch_review_context` | 只读 | viewer+ | 读取上市准备、试销摘要、待审状态和复核令牌 |
| `list_project_lifecycles` | 只读 | viewer+ | 分页读取同一项目从需求、Agent、审批、选品到上市的闭环台账，支持分类汇总、状态筛选和排序 |
| `get_business_dashboard` | 只读 | viewer+ | 返回企业驾驶舱聚合快照 |
| `create_planning_project_draft` | 受控写入 | planner/admin | 幂等创建规划草稿，不触发后续流程 |
| `start_planning_project_analysis` | 受控写入 | planner/admin | 复核当前配置后明确确认并幂等启动 Agent |
| `update_validation_gate` | 受控写入 | planner/admin | 使用最新运行复核令牌单项更新已选方案验证门禁 |
| `submit_launch_review` | 受控写入 | planner/admin | 使用最新上市上下文提交待人工审批的评审单 |
| `claim_approval_task` | 受控写入 | approver/admin | 幂等领取待审批任务，只改变处理人 |
| `submit_approval_decision` | 受控写入 | approver/admin | 使用最新复核令牌和明确确认词提交决定 |

### 规划受控写入安全边界

- 只有 `planner` 和 `admin` 能在工具目录中看到并调用规划受控写入；`viewer` 和 `approver` 不暴露规划写工具。
- 每次调用必须提供稳定的 `request_id`，API 将其映射为 `Idempotency-Key`；相同租户、操作者、操作和请求标识只创建一个项目。
- 相同请求标识和相同参数返回原项目并标记 `replayed=true`；相同标识提交不同参数返回冲突，防止误复用。
- 项目、幂等台账和 `project.created` 审计记录在同一数据库事务内提交，审计会记录 `client=fastmcp` 和请求标识。
- 草稿工具稳定返回 `created_as=draft` 和基于项目名称、品类、市场及完整约束生成的 `review_token`，但不创建规划运行、不投递 Celery，也不触发任何后续业务动作。
- 启动工具必须同时提供当前 `review_token` 和精确确认词 `START_AGENT_ANALYSIS`；项目参数一旦变化，旧令牌立即失效，调用方必须重新读取并复核最新参数。
- FastMCP 只允许启动仍处于 `draft` 状态且未归档的项目；进行中、待审批、已完成或已取消项目不能通过该工具重复启动。
- 规划运行、启动审计和幂等台账在同一 PostgreSQL 事务中创建；相同请求重放返回原运行且不再次投递 Celery，相同请求标识提交不同项目、令牌或确认内容会返回冲突。
- 启动只进入现有 Multi-Agent 与 Celery 执行链路，不会绕过线上审批，不会直接生成正式选品，也不会修改商品立项状态。

### 验证门禁受控写入安全边界

- `update_validation_gate` 仅对 `planner/admin` 可见，每次只能更新当前已选候选方案的一个门禁，不提供批量更新接口。
- 调用前必须使用 `get_planning_run` 读取最新运行；候选方案和已选方案的验证计划都会返回绑定项目、运行状态、候选方案和完整门禁快照的 SHA-256 `review_token`。
- 工具只允许处理 `approval_required` 或 `completed` 运行，且必须提供稳定 `request_id`、最新复核令牌、非空复核说明，以及与 `ready`、`blocked` 或 `pending` 一致的精确确认词。
- 标记为 `ready` 前，该门禁必须已经存在人工通过 Web 上传的有效验证材料；FastMCP 不提供材料上传能力，避免 Agent 自行制造或替换验证凭证。
- 门禁、运行快照、正式选品验证状态、审计事件和幂等台账在同一 PostgreSQL 事务内更新；相同请求重放不会重复写入，相同标识提交不同内容返回冲突。
- 材料上传、门禁状态或运行状态发生变化后旧复核令牌立即失效，调用方必须重新读取并复核最新事实。

### 上市评审受控提交安全边界

- `get_launch_review_context` 返回当前立项状态、前置里程碑、试销经营摘要、上市准备检查、已有待审单、是否可提交及 SHA-256 复核令牌。
- 复核令牌绑定立项、正式选品、运行、负责人、预算、目标日期、备注、完整里程碑、试销汇总、准备度和待审状态；任一业务状态变化后旧令牌立即失效。
- `submit_launch_review` 仅对 `planner/admin` 可见，必须提供稳定请求标识、最新复核令牌、非空评审说明和精确确认词 `SUBMIT_LAUNCH_REVIEW`。
- 评审单、里程碑、审计事件和幂等台账在同一 PostgreSQL 事务内提交；相同请求安全回放，相同请求标识携带不同内容返回冲突。
- MCP 只创建 `pending` 待审单并将上市评审里程碑置为处理中，不自动通过、不自动确认上市，也不开放上市评审决定工具；审批人员继续在 Web 审批中心在线处理。

### 审批受控写入安全边界

- 只有 `approver` 和 `admin` 能看到审批任务、领取工具和决定工具；`viewer` 与 `planner` 不暴露审批能力。
- 领取和决定都必须提供稳定 `request_id`。领取使用通用 PostgreSQL 幂等台账，同一操作者重放只返回原任务；任务已被其他审批人领取时返回冲突。
- `claim_approval_task` 只设置处理人，并返回绑定任务状态、处理人、截止时间和摘要的 SHA-256 `review_token`，不会自动提交任何决定。
- `submit_approval_decision` 必须由当前审批人先领取任务，使用最新 `review_token`，并提供与 `approved`、`rejected` 或 `revision_required` 一致的精确确认词。
- 通过或要求修订必须选择当前审批摘要中的有效候选方案；要求修订只允许修改目标毛利率、售价、成本、供应商、MOQ 和交期，驳回不得携带候选或约束变更且必须填写意见。
- 决定使用任务级幂等标识，相同请求只投递一次 Celery 恢复任务；若队列投递失败，审批状态、决定、处理时间回滚为可重试状态，并记录 `approval.dispatch_failed` 审计事件。
- 成功决定继续进入原有审批恢复链路：通过生成正式选品，要求修订创建子运行版本，驳回取消当前规划运行；MCP 不直接操作这些业务表。

## 后续受控写工具

- 企业部署阶段再评估 OA 回调、批量治理和生产运维类工具；当前不开放任何绕过人工审批或直接确认上市的高风险能力。

所有写工具必须在调用前完成租户、角色、资源归属和幂等校验，调用后写入现有审计台账；高风险操作不提供批量接口。

## 部署路线

1. 本地开发使用独立 `merchpilot-mcp` Docker 服务和 HTTP transport，不改变现有 API 容器。
2. MCP 使用独立可选依赖和 `backend/Dockerfile.mcp`，避免拖重 API/Worker 镜像。
3. 企业部署阶段接入 SSO/OIDC、网关限流、TLS、集中审计和可观测性。
4. 使用 MCP Inspector、工具清单快照和端到端租户隔离测试作为发布门禁。

## 验收标准

- 未认证请求无法列出或调用业务工具。
- 租户 A 无法通过资源 ID、搜索词或分页参数读取租户 B 数据。
- viewer、planner、approver、admin 的工具可见性和调用权限与 Web 系统一致，受控写工具对无权限角色不可见。
- 证据、项目、审批、选品和立项列表均有分页及最大页容量。
- 所有写操作可审计、可幂等，并返回稳定的业务错误结构。
- FastMCP 升级不会改变工具名称、参数 schema 和核心返回字段，除非执行明确版本迁移。

## 本地客户端示例

```python
import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


def local_client_factory(**kwargs):
    kwargs["trust_env"] = False
    return httpx2.AsyncClient(**kwargs)


transport = StreamableHttpTransport(
    "http://127.0.0.1:8001/mcp",
    headers={"Authorization": "Bearer local-profile:viewer"},
    httpx_client_factory=local_client_factory,
)
client = Client(transport)
```

macOS 开发机存在系统 HTTP 代理时需要 `trust_env=False`，否则 `httpx2` 可能把本机请求错误发送到代理。MCP Inspector、curl 或未配置系统代理的客户端无需该处理。

## Web 集成中心

- `GET /api/v1/integrations/mcp?page=1&page_size=6`：探测 MCP 健康状态、使用当前身份读取工具清单，并返回分页后的工具契约与客户端配置。
- `POST /api/v1/integrations/mcp/verify`：以当前身份调用 `get_business_dashboard`，返回项目、审批、正式选品和进行中立项的租户级汇总。
- 集成中心按当前角色统计只读工具和受控写入工具；页面分别说明规划启动、线上审批、验证门禁和上市评审的人工复核、明确确认、最新令牌与幂等边界。
- `GET /api/v1/integrations/mcp/activities?page=1&page_size=5`：只允许规划人员、审批人员和管理员分页查看当前租户的 FastMCP 项目活动。接口按每个项目最近一次 MCP 活动去重分页，返回原始创建人、项目状态，并聚合最近一次 MCP 创建、启动、审批、验证更新和上市评审提交的操作者、请求标识、业务对象、状态和时间，不暴露完整审计详情；审计事件使用自增序号解决同一时间内多次更新的排序歧义。
- Agent 全链路活动卡片将项目、运行、审批、验证和上市评审状态翻译为用户可理解的业务文案，并聚合最近 MCP 创建、启动、审批领取、审批决定、验证门禁更新和上市评审提交；评审卡实时显示人工审批结果并可跳转商品立项，Viewer 无权读取活动列表。
- MCP 不可用时接口返回 `unavailable` 和明确原因，不会让 Web 核心业务、PostgreSQL 或异步任务健康状态被错误判定为不可用。
- 生产身份模式不生成静态真实凭证；页面配置使用访问令牌占位说明，后续应由企业 SSO 或接入网关发放短期 Token。
