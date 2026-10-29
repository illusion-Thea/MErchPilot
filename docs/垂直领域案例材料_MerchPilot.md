# 垂直领域案例材料｜MerchPilot 商品规划与智能选品平台

> 材料日期：2026 年 9 月 7 日  
> 适用场景：案例征集表、简历项目经历、面试项目介绍、AI Agent 垂直领域案例展示  
> 表述原则：区分项目整体能力与个人核心职责，不把企业级预留接口描述为已经正式接入生产环境。

## 一、案例登记表

| 垂直领域 | 案例 | 材料（Markdown 文档） | 链接 | 业务痛点 | 解决方案 | 项目职责 |
| --- | --- | --- | --- | --- | --- | --- |
| 零售电商 / 商品企划 / 智能选品 | MerchPilot 商品规划与选品 Agent 平台 | `docs/垂直领域案例材料_MerchPilot.md`；详细材料：`docs/项目案例介绍_MerchPilot.md` | 本地工作台：`http://localhost:3001`；API 文档：`http://localhost:8000/docs`；FastMCP：`http://localhost:8001/mcp` | 商品、竞品、市场、用户评论、供应商和成本数据分散在 Excel 及不同业务系统中；数据质量和口径不一致；选品依赖个人经验；大模型输出缺少可信证据和可靠数值计算；方案审批、正式选品、商品立项、试销及上市流程相互割裂；任务失败和版本修订难追踪。 | 建设数据治理、RAG 检索、Multi-Agent 规划、确定性财务与供应规则、人在环线上审批、正式选品、商品立项、试销分析和上市评审的一体化平台。PostgreSQL 保存业务事实和审计记录，Milvus 保存证据向量，Redis 承担 Celery、Checkpoint、事件和分布式锁，LangGraph 编排多个 Agent，React 工作台通过 WebSocket 展示实时进度，Docker Compose 提供本地全量运行环境。 | 主要负责证据驱动的 Multi-Agent 规划主链路，包括证据检索、Agent 编排、Prompt 与结构化输出、Celery 异步执行、Redis Checkpoint、失败重试和人工审批恢复；参与 PostgreSQL/Milvus 数据边界、多租户隔离、幂等控制、性能监控及 Docker 联调；配合前端完成规划进度和审批结果展示。 |

> 链接为本地演示地址，需要先执行 `docker compose up -d`。如果案例需要提交到外部平台，应把本地地址替换为代码仓库、部署环境或演示视频链接。

## 二、案例名称

**MerchPilot——面向零售电商商品企划的企业级商品规划与智能选品 Agent 平台**

## 三、垂直领域

- 一级领域：零售电商
- 二级领域：商品企划、商品运营、采购与供应链
- AI 应用方向：企业级 RAG、Multi-Agent、人机协同决策、流程自动化
- 主要用户：商品规划人员、采购人员、供应链人员、财务人员、审批人员和业务管理者

## 四、业务背景与痛点

### 4.1 数据分散且缺少统一口径

商品规划需要同时使用市场趋势、竞品价格、用户评论、历史销量、成本费用、供应商 MOQ 和交期等数据。这些数据通常分散在 Excel、CSV、聊天记录、汇报材料及不同业务系统中，字段命名和统计口径不统一。

### 4.2 选品决策过度依赖个人经验

传统选品往往依赖资深商品人员的经验，不同人员的分析方法、评分标准和风险判断差异较大，难以形成可复制的标准化流程。

### 4.3 通用大模型结果缺少可信依据

直接让通用大模型生成商品方案，容易出现以下问题：

- 推荐结论没有对应的业务证据。
- 销量、价格、成本或用户评价可能被模型虚构。
- 毛利率、盈亏平衡等数值计算不稳定。
- 无法说明某个商品为什么被推荐或淘汰。

### 4.4 分析、审批和商品落地流程断裂

商品方案生成后，还需要经过审批、样品验证、成本确认、供应交付验证、商品立项、试销和上市评审。传统流程依赖人工搬运数据，审批结果与后续业务状态不能自动衔接。

### 4.5 长任务和历史版本难以恢复

商品规划涉及文件解析、向量索引、多个 Agent 调用和模型推理，执行时间较长。发生网络异常、模型超时或服务重启时，需要支持任务重试、状态恢复、已完成节点复用和历史版本追踪。

## 五、解决方案

### 5.1 建立统一数据治理入口

- 支持 Excel、CSV、PDF、PPTX、DOCX 和图片文件导入。
- 使用 `pandas` 和 `openpyxl` 处理结构化表格。
- 使用 Pydantic 校验接口请求和结构化模型输出。
- 统一中文业务字段，处理百分比、万/亿、台/月等业务数值。
- 对必填字段、枚举、日期、来源和内容质量进行逐行校验。
- PostgreSQL 保存原始来源、规范化结果、质量状态和审计信息。

### 5.2 建设可追溯的 RAG 证据链

- 使用 BGE-M3 生成证据向量并写入 Milvus。
- 根据租户、品类和目标市场执行向量过滤。
- 使用 BGE Reranker 对召回结果重新排序。
- Milvus 负责候选召回，PostgreSQL 负责最终权限、质量状态和来源校验。
- Agent 输出必须引用允许使用的证据 ID；没有证据支持的内容只能标记为假设或待验证项。

### 5.3 使用 LangGraph 编排 Multi-Agent 规划流程

核心执行链路包括：

1. Requirement Agent：规范化业务需求和规划约束。
2. Research Planning Agent：设计市场、竞品和用户洞察检索策略。
3. Market / Competitor / User Insight：并行完成多源证据研究。
4. Research Synthesis：治理证据冲突、缺口和可信度。
5. Concept Agent：生成差异化候选商品概念。
6. Supplier Tool：评估 MOQ、交期和供应风险。
7. Finance Engine：计算售价、成本、毛利率及盈亏平衡。
8. Scoring Engine：生成可解释的机会评分。
9. Critic Agent：检查证据不足、逻辑冲突和模型幻觉。
10. Narrative Agent：形成管理层摘要和行动建议。
11. Human Review Gate：创建线上审批任务并暂停自动流程。

### 5.4 将模型能力和确定性规则分离

- 大模型负责需求理解、研究归纳、候选概念和管理层建议。
- 财务指标、供应阻断条件、状态转换等使用确定性代码计算。
- 关键输出通过 Pydantic Schema 校验，失败时执行重试或可解释降级。
- Agent 不能自动完成最终审批、正式选品或上市确认。

### 5.5 建立人在环线上审批闭环

- Agent 分析完成后自动生成系统内审批任务。
- 审批人员可以查看证据、候选方案、财务测算、供应风险和评分拆解。
- 支持通过、驳回、要求修订、任务认领、释放和转派。
- 要求修订时创建关联父运行的新版本，并继承审批意见和必要验证材料。
- 审批通过后自动生成正式选品记录，继续进入验证、立项、试销和上市评审。

### 5.6 保障异步任务可靠性和高并发能力

- Celery 按规划 Agent、数据索引和报告任务拆分队列及 Worker。
- Redis 保存消息、运行 Checkpoint、实时事件、限流计数和分布式锁。
- WebSocket 向前端推送节点状态、执行进度和审批等待状态。
- 使用项目级、运行级和 Agent 节点级分布式锁防止重复执行。
- 模型服务增加舱壁隔离、排队超时和熔断机制。
- Prometheus 采集 API 延迟、数据库查询、慢 SQL、队列积压、Worker 和模型服务指标。

## 六、技术架构

| 层次 | 技术栈 | 主要用途 |
| --- | --- | --- |
| 前端工作台 | React、Next.js、Redux Toolkit、Ant Design、AntV X6/Charts、Axios、WebSocket | 业务模块、实时进度、Agent Mesh、审批和运营展示 |
| API 层 | FastAPI、Pydantic、SQLAlchemy | REST API、身份依赖、业务校验、数据库访问 |
| Agent 层 | LangGraph、LangChain、Qwen/DashScope、结构化 Prompt | Multi-Agent 编排、模型调用和结构化输出 |
| 异步任务 | Celery、Redis | 长任务、重试、队列拆分、Checkpoint 和事件流 |
| 业务事实库 | PostgreSQL | 项目、运行、审批、证据、选品、立项、试销和审计 |
| 向量检索 | Milvus、BGE-M3、BGE Reranker | 证据向量化、语义召回和候选重排 |
| 能力开放 | FastMCP | 向外部 Agent 提供带权限和确认门禁的业务工具 |
| 运维与部署 | Docker Compose、Prometheus | 本地全量部署、健康检查、指标和性能观察 |

## 七、项目职责

### 7.1 推荐填写版本

主要负责证据驱动的异步 Multi-Agent 商品规划链路设计与开发。完成 PostgreSQL 与 Milvus 协同的 RAG 检索流程、LangGraph Agent 编排、Prompt 和 Pydantic 结构化输出、Celery 长任务、Redis Checkpoint、失败重试及人工审批恢复；参与多租户数据隔离、接口幂等、分布式锁、模型熔断、Prometheus 指标及 Docker Compose 联调；配合前端实现 Agent 节点进度、规划结果和审批状态的实时展示。

### 7.2 简历精简版本

- 负责商品规划 Multi-Agent 核心链路，使用 LangGraph 编排需求分析、多源研究、概念生成、供应评估、财务测算、机会评分和人工审批节点。
- 建设 PostgreSQL + Milvus 的企业 RAG 证据链，通过租户过滤、质量复核、向量召回、Reranker 和证据 ID 约束降低模型幻觉。
- 使用 Celery + Redis 实现长任务队列拆分、Checkpoint、失败重试、断点恢复、WebSocket 实时进度和分布式锁。
- 将 LLM 生成与财务、供应及业务状态规则分离，使用 Pydantic 校验结构化输出，保障核心数值和流程状态可控。
- 参与线上审批、正式选品、商品立项和上市评审的状态衔接，以及 Docker、Prometheus 和性能压测建设。

### 7.3 面试口述版本

> 我主要负责的是证据驱动的异步 Multi-Agent 规划主链路。业务数据先经过质量治理进入 PostgreSQL，可检索证据通过 BGE-M3 写入 Milvus。规划任务由 Celery 异步执行，LangGraph 编排需求理解、市场研究、竞品分析、用户洞察、概念生成、供应评估、财务测算和机会评分。模型生成的内容必须引用证据 ID，财务和供应规则使用确定性代码计算。流程最后进入系统内人工审批，审批要求修订时可以创建新版本，并从 Redis Checkpoint 和 PostgreSQL 快照恢复。系统整体还包括正式选品、立项、试销和上市评审，我能够说明这些模块的状态衔接，但个人重点开发范围是 RAG、Agent 编排、异步任务和审批恢复。

## 八、案例价值

- 将分散的商品数据沉淀为可治理、可检索、可引用的企业证据资产。
- 将依赖个人经验的商品规划拆解为标准化、可复用的 Agent 工作流。
- 使用确定性规则和人工门禁控制模型幻觉及业务风险。
- 打通分析、审批、正式选品、立项、试销和上市评审的业务状态。
- 支持任务恢复、版本追踪、多租户隔离和操作审计，满足企业系统基本可靠性要求。

## 九、演示与材料链接

本地环境启动命令：

```bash
docker compose up -d
```

- Web 工作台：`http://localhost:3001`
- API 文档：`http://localhost:8000/docs`
- API 健康检查：`http://localhost:8000/health/ready`
- FastMCP：`http://localhost:8001/mcp`
- Prometheus：`http://localhost:9090`
- 完整案例说明：`docs/项目案例介绍_MerchPilot.md`
- 面试项目介绍：`docs/interview-project-introduction.md`
- 个人开发范围：`docs/interview-development-scope.md`
- 系统架构说明：`docs/architecture.md`
