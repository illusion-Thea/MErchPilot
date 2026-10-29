# 垂直领域公开案例对标｜MerchPilot

> 整理日期：2026 年 9 月 7 日  
> 使用场景：垂直领域案例登记、项目立项背景、竞品分析、简历和面试材料  
> 说明：本文中的沃尔玛、迪卡侬案例均来自网络公开资料，不代表本人参与过对应企业项目。“项目职责”是指在 MerchPilot 项目中参考这些案例所承担的对应开发职责。

## 一、推荐提交版本

| 垂直领域 | 公开案例 | 材料（Markdown 文档） | 公开链接 | 业务痛点 | 公开案例解决方案 | MerchPilot 对应项目职责 |
| --- | --- | --- | --- | --- | --- | --- |
| 零售电商 / 商品企划 / 智能选品 | Walmart Trend-to-Product | `docs/垂直领域公开案例对标_MerchPilot.md` | [Walmart：In an Ever-Changing Environment, Walmart Uses GenAI To Create Cool for Customers](https://corporate.walmart.com/news/2025/04/09/in-an-ever-changing-environment-walmart-uses-genai-to-create-cool-for-customers) | 时尚趋势来源分散，设计师需要人工研究社交媒体、秀场和趋势服务；从趋势研究、概念设计到供应商生产的传统流程周期长，商品容易错过趋势窗口；AI生成结果仍需要结合销售表现和商品人员经验判断。 | Trend-to-Product 使用 AI 和生成式 AI 汇总全球趋势数据，自动辅助生成主题、色彩、材质、款式构想和情绪板，再由设计师与商品人员结合售罄数据进行人工调整，最后生成供应商生产所需的技术包。沃尔玛公开资料称，该工具把研究和设计阶段从数周压缩到分钟级，整体流程约一小时，商品从概念到上架缩短到约6—8周，较传统流程最多减少18周。 | 负责 MerchPilot 中与该案例对应的证据驱动商品企划链路：建设趋势、竞品、评论、销售、成本和供应商数据的 RAG 证据检索；使用 LangGraph 编排市场研究、竞品分析、用户洞察、概念生成、供应评估、财务测算和机会评分 Agent；通过 Pydantic 约束结构化输出和证据引用；使用 Celery、Redis Checkpoint 支持长任务、重试及恢复；建设系统内人工审批和方案修订闭环。 |

这是与 MerchPilot 业务最接近、最适合优先提交的公开案例。

## 二、补充公开案例

| 垂直领域 | 公开案例 | 公开链接 | 业务痛点 | 公开案例解决方案 | 与 MerchPilot 的对应关系 |
| --- | --- | --- | --- | --- | --- |
| 零售电商 / 商品运营 / 商品分析 | Walmart Wally 商品人员 GenAI 助手 | [Walmart Develops GenAI-Powered Assistant for Walmart Merchants](https://corporate.walmart.com/news/2025/03/18/walmart-develops-genai-powered-assistant-for-walmart-merchants) | 商品人员需要跨门店、区域、渠道、SKU和品牌运行多份报表，并在复杂表格中分析商品表现，数据查询、指标计算和异常归因耗时。 | Wally 基于沃尔玛内部数据和零售语义层，支持自然语言查询、数据分析、商品表现异常归因、业务操作问答、工单处理以及复杂公式和预测计算。沃尔玛还提出在可配置业务边界内，将其从助手逐步发展为能够执行战术动作的 Agent。 | 对应 MerchPilot 的数据语义统一、自然语言业务分析、确定性指标计算、商品评分解释、Agent 工具调用、权限隔离和人工操作门禁。 |
| 零售 / 供应链 / 需求预测 | Decathlon Chronos-2 全球需求预测 | [AWS：How Decathlon runs demand forecasting at scale with Chronos-2](https://aws.amazon.com/blogs/machine-learning/how-decathlon-runs-demand-forecasting-at-scale-with-chronos-2/) | 多地区、数万商品、不同运动品类的季节性需求差异明显；既要支持12周补货，又要支持52周战略库存规划；原有模型需要频繁重新训练，扩展新区域的工程成本较高。 | 迪卡侬使用 Chronos-2 时间序列基础模型构建全球需求预测流程，通过 PySpark 准备数据、AutoGluon与LoRA进行低频微调、MLflow管理模型，并执行每周批量预测。公开资料称，其12周预测的WAPE改善11—15个百分点，新区域部署时间由6个月缩短至2—3个月。 | 对应 MerchPilot 的销量预测、补货建议、供应风险和试销复盘扩展方向。当前项目重点是商品企划和选品 Agent，需求预测可以作为后续独立模型服务接入，不应描述为当前已经完整落地。 |

## 三、主案例分析：Walmart Trend-to-Product

### 3.1 案例背景

沃尔玛在 2025 年 4 月公开了 Trend-to-Product。该工具面向服装设计师和商品人员，将互联网、趋势人士和其他全球趋势数据进行分析和综合，辅助完成从趋势发现到商品概念设计的工作。

其业务流程并不是让大模型直接决定最终商品，而是采用“AI生成 + 人工判断”的协作模式：

1. AI分析全球趋势和外部信息。
2. 生成系列主题、颜色、纹理、款式创意和情绪板。
3. 设计师和商品人员结合售罄数据与业务经验修改方案。
4. 系统生成供应商可以使用的商品技术包。
5. 供应商按照技术要求完成生产与交付。

### 3.2 核心业务痛点

- 趋势信息散落在社交媒体、秀场、杂志、街头及趋势服务中。
- 设计师需要承担大量信息搜索、整理和归纳工作。
- 趋势变化速度快，而传统商品开发周期约为数月。
- 纯AI生成不能替代售罄数据、供应可行性和专业人员判断。
- 从概念到供应商生产文件之间存在大量人工转换工作。

### 3.3 公开效果

根据沃尔玛官方公开材料：

- 研究与设计阶段由数周压缩到分钟级。
- 一轮趋势到设计技术包的流程约为一小时。
- 商品从概念到门店及线上销售约需6—8周。
- 相比传统方式，整体商品上市时间最多减少18周。
- 系统保留设计师和商品人员的最终判断，不是完全自动决策。

### 3.4 与 MerchPilot 的对应关系

| Walmart Trend-to-Product | MerchPilot |
| --- | --- |
| 汇总全球趋势信息 | 导入市场、竞品、评论、销售和供应商数据，并建立统一数据质量规则 |
| AI分析和综合趋势 | PostgreSQL业务事实 + Milvus证据向量 + BGE检索和重排 |
| 自动生成主题和商品构想 | LangGraph Multi-Agent生成需求分析、市场研究和商品概念 |
| 商品人员结合售罄数据修订 | 商品评分、销量证据、毛利测算及系统内人工审批 |
| 生成供应商技术包 | 输出结构化商品方案、规格、成本和供应要求 |
| 人员主导、技术辅助 | 人在环审批、驳回修订、版本追踪和操作审计 |

## 四、项目职责表述

### 4.1 案例登记表版本

参考 Walmart Trend-to-Product 和 Wally 等公开零售AI案例，负责 MerchPilot 证据驱动的商品规划与智能选品核心链路建设。完成 PostgreSQL 与 Milvus 协同的业务数据和证据检索体系，使用 LangGraph 编排市场研究、竞品分析、用户洞察、概念生成、供应评估、财务测算与机会评分 Agent；设计 Prompt、工具调用和 Pydantic 结构化输出约束；通过 Celery、Redis Checkpoint、幂等锁和重试机制支持长任务可靠执行；建设人工审批、方案修订和版本恢复流程，并配合 React 前端实现 Agent 进度与审批状态的实时展示。

### 4.2 简历版本

- 调研 Walmart Trend-to-Product、Wally 等零售AI公开案例，拆解趋势分析、商品企划、经营分析和人在环决策流程。
- 负责 PostgreSQL + Milvus 的商品知识与证据链，支持多租户过滤、向量召回、Reranker重排和证据ID引用。
- 使用 LangGraph 构建商品规划 Multi-Agent 工作流，覆盖市场研究、竞品分析、用户洞察、商品概念、供应评估和财务测算。
- 使用 Celery + Redis 实现长任务异步执行、Checkpoint、失败重试、断点恢复、分布式锁和WebSocket进度事件。
- 使用确定性代码处理毛利、成本和供应规则，并通过 Pydantic 校验模型结构化输出，降低大模型幻觉风险。
- 建设系统内人工审批、驳回修订和版本追踪闭环，保证关键商品决策由业务人员最终确认。

### 4.3 面试表述边界

推荐说法：

> 项目前期参考了 Walmart Trend-to-Product 和 Wally 等公开案例。我主要负责在 MerchPilot 中实现相似业务思想下的 RAG、Multi-Agent、异步任务和人在环审批能力。

不推荐说法：

> 我参与开发了 Walmart Trend-to-Product 或 Wally。

公开案例只能作为业务调研和方案对标依据，不能描述为个人参与项目。

## 五、公开资料来源

1. Walmart，2025-04-09：[In an Ever-Changing Environment, Walmart Uses GenAI To Create Cool for Customers](https://corporate.walmart.com/news/2025/04/09/in-an-ever-changing-environment-walmart-uses-genai-to-create-cool-for-customers)
2. Walmart，2025-03-18：[Walmart Develops GenAI-Powered Assistant for Walmart Merchants](https://corporate.walmart.com/news/2025/03/18/walmart-develops-genai-powered-assistant-for-walmart-merchants)
3. Walmart，2025-05-29：[Inside Walmart’s Strategy for Building an Agentic Future](https://corporate.walmart.com/news/2025/05/29/inside-walmarts-strategy-for-building-an-agentic-future)
4. AWS / Decathlon，2026-08-28：[How Decathlon runs demand forecasting at scale with Chronos-2](https://aws.amazon.com/blogs/machine-learning/how-decathlon-runs-demand-forecasting-at-scale-with-chronos-2/)

