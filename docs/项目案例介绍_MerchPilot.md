## **项目一：商品规划与智能选品领域——MerchPilot 商品规划与选品 Agent 平台**

### 项目背景：

- 传统商品规划通常依赖商品运营、市场研究、采购、供应链、财务和审批人员协同完成。市场趋势、竞品信息、用户评价、成本、供应商和历史销量分散在 Excel、CSV、业务系统和人工汇报材料中，数据口径不一致，研究结论难复用，也很难追溯某个商品方案为什么被推荐。
- 商品规划本身不是简单的文本生成任务。它既需要从大量非结构化和半结构化数据中提取证据，也需要完成价格、成本、毛利、销量、盈亏平衡、MOQ、交期等确定性计算，还要经过人工审批、正式选品、验证、试销和上市评审等业务门禁。
- 如果只使用一个通用大模型或聊天机器人，容易出现证据引用不完整、数值计算不可靠、推荐结果无法审批、审批通过后无法进入商品落地以及历史版本无法追溯等问题。因此，本项目将商品规划拆解为可编排的多 Agent 节点，并把规则计算、数据治理、人工审批和业务状态机纳入同一套系统。
- 项目目标不是输出一份静态商品报告，而是建立一条“数据治理 → 证据检索 → Multi-Agent 分析 → 线上审批 → 正式选品 → 商品验证 → 商品立项 → 试销评估 → 上市评审”的企业级业务闭环。

### 业务逻辑：

- 架构图：

  ```mermaid
  %%{init: {"theme":"base","themeVariables":{"background":"#0f172a","primaryColor":"#1d4ed8","primaryTextColor":"#ffffff","nodeTextColor":"#ffffff","primaryBorderColor":"#bfdbfe","lineColor":"#e2e8f0","textColor":"#ffffff","clusterBkg":"#1e293b","clusterBorder":"#cbd5e1","titleColor":"#ffffff","edgeLabelBackground":"#0f172a","edgeLabelTextColor":"#ffffff","fontSize":"17px","fontFamily":"Arial, PingFang SC, Microsoft YaHei, sans-serif"}}}%%
  flowchart TB
      USER[商品运营 / 采购 / 供应链 / 财务 / 审批人员]
      WEB[React + Next.js 业务工作台]
      API[FastAPI 业务 API + WebSocket]
      CELERY[Celery 异步任务]
      MCP[FastMCP 能力开放层]
      POSTGRES[(PostgreSQL 业务事实库)]
      REDIS[(Redis 队列 / Checkpoint / 事件)]
      MILVUS[(Milvus 证据向量索引)]
      EMBED[BGE-M3 Embedding]
      RERANK[BGE Reranker]
      MODEL[DashScope Qwen / LLM]
      RULES[确定性财务 / 供应规则]
      FILES[本地文件卷 / OSS 适配器]

      subgraph MESH_LAYER["LangGraph Multi-Agent Mesh：共享 MeshState 的协作层"]
          REQ[Requirement Agent<br/>需求规范化]
          MARKET[Market Tool<br/>市场研究]
          COMP[Competitor Tool<br/>竞品分析]
          INSIGHT[User Insight Tool<br/>用户洞察]
          CONCEPT[Concept Agent<br/>候选概念]
          SUPPLIER[Supplier Tool<br/>供应商评估]
          FINANCE[Finance Engine<br/>财务测算]
          SCORE[Scoring Engine<br/>机会评分]
          NARRATIVE[Narrative Agent<br/>规划建议]
          REVIEW[review_agent<br/>人工审批门禁]

          REQ --> MARKET
          REQ --> COMP
          REQ --> INSIGHT
          MARKET --> CONCEPT
          COMP --> CONCEPT
          INSIGHT --> CONCEPT
          CONCEPT --> SUPPLIER
          CONCEPT --> FINANCE
          SUPPLIER --> SCORE
          FINANCE --> SCORE
          SCORE --> NARRATIVE
          NARRATIVE --> REVIEW
      end

      USER --> WEB
      WEB --> API
      MCP --> API
      API --> POSTGRES
      API --> REDIS
      API --> CELERY
      API --> FILES
      CELERY --> REQ
      CELERY --> EMBED
      EMBED --> MILVUS
      NARRATIVE --> POSTGRES
      REQ -.共享执行状态.-> REDIS
      MARKET -.检索候选证据.-> MILVUS
      SCORE -.重排候选证据.-> RERANK
      NARRATIVE -.模型调用.-> MODEL
      FINANCE -.确定性计算.-> RULES
      SUPPLIER -.确定性校验.-> RULES
      REVIEW -.审批决定回写.-> POSTGRES

      classDef agent fill:#1d4ed8,stroke:#bfdbfe,stroke-width:2px,color:#ffffff,font-weight:700;
      classDef gate fill:#b45309,stroke:#fde68a,stroke-width:2px,color:#ffffff,font-weight:700;
      classDef system fill:#334155,stroke:#cbd5e1,stroke-width:1.5px,color:#ffffff,font-weight:700;
      class REQ,MARKET,COMP,INSIGHT,CONCEPT,SUPPLIER,FINANCE,SCORE,NARRATIVE agent;
      class REVIEW gate;
      class USER,WEB,API,CELERY,MCP,POSTGRES,REDIS,MILVUS,EMBED,RERANK,MODEL,RULES,FILES system;
      style USER fill:#334155,stroke:#cbd5e1,color:#ffffff
      style WEB fill:#334155,stroke:#cbd5e1,color:#ffffff
      style API fill:#334155,stroke:#cbd5e1,color:#ffffff
      style CELERY fill:#334155,stroke:#cbd5e1,color:#ffffff
      style MCP fill:#334155,stroke:#cbd5e1,color:#ffffff
      style POSTGRES fill:#334155,stroke:#cbd5e1,color:#ffffff
      style REDIS fill:#334155,stroke:#cbd5e1,color:#ffffff
      style MILVUS fill:#334155,stroke:#cbd5e1,color:#ffffff
      style EMBED fill:#334155,stroke:#cbd5e1,color:#ffffff
      style RERANK fill:#334155,stroke:#cbd5e1,color:#ffffff
      style MODEL fill:#334155,stroke:#cbd5e1,color:#ffffff
      style RULES fill:#334155,stroke:#cbd5e1,color:#ffffff
      style FILES fill:#334155,stroke:#cbd5e1,color:#ffffff
      style REQ fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style MARKET fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style COMP fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style INSIGHT fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style CONCEPT fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style SUPPLIER fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style FINANCE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style SCORE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style NARRATIVE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style REVIEW fill:#b45309,stroke:#fde68a,color:#ffffff
      linkStyle default stroke:#e2e8f0,stroke-width:2px;
  ```

  - **业务工作台层**：使用 React、Next.js、Ant Design、Redux Toolkit、Axios、AntV 和 WebSocket，为不同角色提供业务驾驶舱、数据治理、规划执行、线上审批、正式选品、商品立项、Agent 集成和运维审计模块。
  - **API 业务服务层**：使用 FastAPI 提供项目、运行、导入、检索、审批、选品、商品立项、报告、分析、审计和 WebSocket 接口，统一处理身份、租户、权限、参数校验和业务规则。
  - **异步任务层**：使用 Celery + Redis 承载表格导入、Embedding、Milvus 索引、Agent 规划运行、报告生成和失败恢复等长耗时任务，避免阻塞 API 请求。
  - **Agent 编排层**：使用 LangGraph 构建 5 个规划 LLM Agent、7 个确定性业务工具和 1 个人工审批门禁节点；数据导入流水线另接入 1 个 Qwen-VL 多模态 LLM Agent。市场、竞品和用户洞察工具可以并行执行；供应商评估和财务测算工具可以并行执行；最终统一进入评分、方案审查、规划建议和人工审批。目录共登记 14 个节点，规划图实际执行其中 13 个。
  - **节点协作关系**：所有规划节点共享同一个 `MeshState`。`Requirement Agent` 负责准备上下文并向三路研究工具分发任务；市场、竞品、用户洞察完成后汇合到 `Concept Agent`；概念生成后再分发给供应商和财务工具；`Scoring` 和 `Narrative Agent` 负责统一收敛，`review_agent` 将结果交给审批人员决定。
  - **数据与检索层**：PostgreSQL 保存项目、运行、审批、选品、立项、验证材料、试销和审计等权威事实；Milvus 保存证据向量索引；Redis 保存 Celery 队列、Checkpoint、锁和实时事件。
  - **能力开放层**：使用独立 FastMCP 服务向外部 Agent、IDE 助手和自动化工作流开放受权限、确认词、幂等和审计约束的业务工具。FastMCP 通过既有 FastAPI 调用业务能力，不直连数据库，不产生第二套业务规则。
  - **企业扩展层**：当前本地 Docker 使用本地身份、文件卷、内部审批和控制台遥测；通过 Provider/Adapter 接口为企业 SSO、OA、阿里云 OSS 和监控平台预留替换点。

- Agent 工作流：

  **数据采集与质量治理 → 规划项目配置 → 需求分析 → 市场/竞品/用户洞察并行检索 → 商品概念生成 → 供应商/财务并行评估 → 机会评分 → 规划建议 → 系统内线上审批 → 正式选品 → 验证门禁 → 商品立项 → 试销评估 → 上市准备评审 → 上市确认与经营复盘**。

- Agent 协作工作流图：

  ```mermaid
  %%{init: {"theme":"base","themeVariables":{"background":"#0f172a","primaryColor":"#334155","primaryTextColor":"#ffffff","nodeTextColor":"#ffffff","primaryBorderColor":"#cbd5e1","lineColor":"#e2e8f0","textColor":"#ffffff","clusterBkg":"#1e293b","clusterBorder":"#cbd5e1","titleColor":"#ffffff","edgeLabelBackground":"#0f172a","edgeLabelTextColor":"#ffffff","fontSize":"17px","fontFamily":"Arial, PingFang SC, Microsoft YaHei, sans-serif"}}}%%
  flowchart TD
      START([启动规划运行]) --> REQ[Requirement Agent<br/>规范化需求与规划约束]

      subgraph RESEARCH[并行研究阶段]
          MARKET[Market Tool<br/>市场趋势与机会]
          COMP[Competitor Tool<br/>竞品与差异化]
          INSIGHT[User Insight Tool<br/>用户痛点与场景]
      end
      REQ --> MARKET
      REQ --> COMP
      REQ --> INSIGHT

      MARKET --> EVIDENCE[证据汇合<br/>统一写入 MeshState]
      COMP --> EVIDENCE
      INSIGHT --> EVIDENCE
      EVIDENCE --> CONCEPT[Concept Agent<br/>生成 3 个候选商品概念]

      subgraph EVALUATION[并行评估阶段]
          SUPPLIER[Supplier Tool<br/>MOQ / 交期 / 供应风险]
          FINANCE[Finance Engine<br/>成本 / 毛利 / 盈亏平衡]
      end
      CONCEPT --> SUPPLIER
      CONCEPT --> FINANCE

      SUPPLIER --> SCORE[Scoring Engine<br/>输出可解释机会评分]
      FINANCE --> SCORE
      SCORE --> NARRATIVE[Narrative Agent<br/>生成推荐理由与风险摘要]
      NARRATIVE --> REVIEW[review_agent<br/>创建线上审批任务]
      REVIEW --> WAIT[(approval_required<br/>保存 Checkpoint 并暂停)]
      WAIT --> HUMAN{审批人员在线决定}

      HUMAN -->|通过| SELECTED[正式选品台账]
      HUMAN -->|要求修订| REVISION[创建子运行<br/>继承必要材料与上下文]
      HUMAN -->|驳回| REJECT[结束运行<br/>保留完整历史]
      REVISION --> REQ

      SELECTED --> GATES[四道验证门<br/>需求 / 样品 / 商业 / 供应]
      GATES --> INITIATIVE[商品立项五里程碑]
      INITIATIVE --> PILOT[小批量试销与经营评估]
      PILOT --> LAUNCH[上市准备评审]
      LAUNCH --> END([上市确认或形成复盘记录])

      REQ -.节点事件.-> EVENTS[(Redis Stream / WebSocket)]
      CONCEPT -.证据检索.-> RETRIEVAL[(Milvus + PostgreSQL 权威回查)]
      FINANCE -.确定性规则.-> RULES[Finance / Supplier Rules]

      classDef flow fill:#334155,stroke:#cbd5e1,stroke-width:1.5px,color:#ffffff,font-weight:700;
      classDef control fill:#b45309,stroke:#fde68a,stroke-width:2px,color:#ffffff,font-weight:700;
      class START,REQ,MARKET,COMP,INSIGHT,EVIDENCE,CONCEPT,SUPPLIER,FINANCE,SCORE,NARRATIVE,WAIT,SELECTED,REVISION,REJECT,GATES,INITIATIVE,PILOT,LAUNCH,END,EVENTS,RETRIEVAL,RULES flow;
      class HUMAN,REVIEW control;
      style START fill:#334155,stroke:#cbd5e1,color:#ffffff
      style REQ fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style MARKET fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style COMP fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style INSIGHT fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style EVIDENCE fill:#334155,stroke:#cbd5e1,color:#ffffff
      style CONCEPT fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style SUPPLIER fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style FINANCE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style SCORE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style NARRATIVE fill:#1d4ed8,stroke:#bfdbfe,color:#ffffff
      style REVIEW fill:#b45309,stroke:#fde68a,color:#ffffff
      style WAIT fill:#334155,stroke:#cbd5e1,color:#ffffff
      style HUMAN fill:#b45309,stroke:#fde68a,color:#ffffff
      style SELECTED fill:#334155,stroke:#cbd5e1,color:#ffffff
      style REVISION fill:#334155,stroke:#cbd5e1,color:#ffffff
      style REJECT fill:#334155,stroke:#cbd5e1,color:#ffffff
      style GATES fill:#334155,stroke:#cbd5e1,color:#ffffff
      style INITIATIVE fill:#334155,stroke:#cbd5e1,color:#ffffff
      style PILOT fill:#334155,stroke:#cbd5e1,color:#ffffff
      style LAUNCH fill:#334155,stroke:#cbd5e1,color:#ffffff
      style END fill:#334155,stroke:#cbd5e1,color:#ffffff
      style EVENTS fill:#334155,stroke:#cbd5e1,color:#ffffff
      style RETRIEVAL fill:#334155,stroke:#cbd5e1,color:#ffffff
      style RULES fill:#334155,stroke:#cbd5e1,color:#ffffff
      linkStyle default stroke:#e2e8f0,stroke-width:2px;
  ```

  - **图中最重要的协作点**：实线表示工作流依赖，分叉表示可并行执行，汇合表示必须等待上游结果；虚线表示 Agent 使用的共享能力，不代表新增业务流程。
  - **人工边界**：`review_agent` 只负责创建审批任务和暂停运行，审批通过、要求修订或驳回均由系统内审批人员在线决定；Agent 不直接替代业务责任人。

- Agent 设计：

  | Agent / 节点角色 | 核心职责 | 对应业务阶段 |
  | --- | --- | --- |
  | **Requirement Agent** | 规范化品类、目标市场、规划约束、目标用户和业务输入，形成统一规划上下文 | 需求分析 |
  | **Market Tool** | 根据品类和市场条件检索趋势、销量、价格、库存等证据，输出带来源的检索结果 | 市场研究 |
  | **Competitor Tool** | 检索竞品信息、价格、功能、评价和差异化特征，输出带来源的检索结果 | 竞品分析 |
  | **User Insight Tool** | 检索用户评价和反馈，归纳用户痛点、需求标签、使用场景和风险 | 用户洞察 |
  | **Concept Agent** | 综合市场、竞品、用户洞察和规划指标，生成 3 个可比较的候选商品概念，并输出候选评分和验证计划 | 商品概念 |
  | **Supplier Tool** | 评估供应商完整性、MOQ、交期、可交付性和供应风险 | 供应商评估 |
  | **Finance Engine** | 使用确定性规则计算售价、单位成本、费用、毛利、毛利率、盈亏平衡和预计利润 | 财务测算 |
  | **Scoring Engine** | 综合证据适配度、商业可行性、供应和数据准备度，生成可解释机会评分 | 机会评分 |
  | **Narrative Agent** | 将结构化结果转换为管理层摘要、推荐理由、风险和下一步行动 | 规划建议 |
  | **review_agent 人工门禁节点** | 创建系统内线上审批任务，将运行状态切换为 `approval_required`，等待审批人员决定 | 人工审批 |
  | **统一工具与业务服务层** | 提供 PostgreSQL、Redis、Milvus、Embedding、Reranker、财务规则、供应规则、对象存储、审批和审计能力 | 全流程共用 |

- 工作流：

  ```text
  用户创建规划项目
      ↓
  Requirement Agent：规范化规划约束
      ↓
  ┌──────────────── Market Tool：市场研究 ─────────────────┐
  ├──────────────── Competitor Tool：竞品分析 ─────────────┤  并行执行
  └──────────────── User Insight Tool：用户洞察 ───────────┘
      ↓ 三路证据汇合
  Concept Agent：生成 3 个候选商品概念与验证计划
      ↓
  ┌──────────────── Supplier Tool：供应商评估 ──────────────┐
  └──────────────── Finance Engine：财务测算 ───────────────┘  并行执行
      ↓ 两路结果汇合
  Scoring Engine：输出 100 分可解释评分
      ↓
  Narrative Agent：输出规划建议、风险和管理层摘要
      ↓
  review_agent：创建系统内线上审批任务
      ↓
  审批通过：生成正式选品台账
      ├─ 要求修订：生成子运行，继承必要材料和验证上下文后重新执行
      └─ 驳回：运行结束，保留完整审批和运行历史
      ↓
  四道验证门：需求匹配 / 规格样品 / 商业可行 / 供应交付
      ↓ 验证材料齐全且人工确认通过
  商品立项：项目启动 → 样品定版 → 成本定版 → 小批量试销 → 上市准备评审
      ↓
  试销经营评估 + 系统内线上上市评审
      ↓
  上市确认 / 要求修订 / 驳回，最终形成经营复盘记录
  ```

- 状态特点：

  - 自动 Agent 只负责证据检索、结构化分析、规则调用和文本建议，不替代审批人员作出最终业务决定。
  - 财务、供应和试销指标由程序规则计算，避免让大模型直接计算关键经营数字。
  - 规划运行完成后必须进入系统内线上审批，审批结果才会驱动正式选品和后续商品流程。
  - 审批要求修订时不覆盖原运行，而是生成带 `parent_run_id` 和 `revision_no` 的新运行，保留历史决策链路。
  - 验证门禁在标记为 ready 前必须存在有效人工材料，不能由 Agent 自动伪造验证依据。
  - 上市准备评审和确认上市是两个独立动作，Agent 可以准备材料，但不能自动确认上市。

### 相关工作：

整体分为**数据治理与检索、工作流编排、多 Agent 业务能力、异步执行与状态、业务闭环与人机协同、统一能力开放、质量与审计**7 大块。项目坚持以下原则：**事实数据交给数据库，确定性计算交给规则引擎，语义检索交给向量系统，文本理解和总结交给大模型，最终业务责任保留给人工审批人员。**

#### 1. 数据治理与证据检索层

1. 设计版本化的 37 字段数据采集模板，支持 Excel/CSV 上传、模板字段和历史字段别名归一化。
2. 使用 `pandas` 对表格进行解析，处理空行、日期、百分比、单位、枚举值和文本长度，并保留未知中文列和原始数值，避免采集数据在清洗过程中无声丢失。
3. 在 PostgreSQL 中保存导入批次、证据记录、质量问题、内容哈希、来源 ID、来源行号、观察日期、索引状态和来源链路。
4. 对相同来源 ID 和相同内容哈希进行重复候选分析，支持规划人员或管理员选择规范记录、保留全部记录或忽略重复候选。
5. 使用 Celery 将可索引证据分批发送给 BGE-M3 Embedding 服务，成功批次及时写入 Milvus，失败批次单独隔离和重试。
6. 检索流程先在 Milvus 中召回候选证据 ID，再回 PostgreSQL 校验当前租户、质量状态、索引状态和重复治理结果，Milvus 不作为业务事实源。
7. 使用 BGE Reranker 对候选证据重排，返回向量分数、重排分数、来源元数据和降级原因；前端不把模型分数错误展示成百分比。
8. 模型或向量服务不可用时，记录显式 degraded/partial 原因，保留可诊断结果，主流程仍能进入系统内线上评审。

#### 2. 主控调度与规划运行层（核心骨架）

1. 使用 LangGraph `StateGraph` 定义 `MeshState`，统一承载 `run_id`、请求参数、Agent 输出、运行状态、审批标识、恢复节点和运行指标。
2. 定义 13 个规划 Mesh 节点，并在 Agent Catalog 中登记导入流水线多模态 LLM Agent；规划节点按 LLM Agent、确定性业务工具和 `review_agent` 人工审批门禁分层，统一包装节点生命周期事件。
3. 实现市场、竞品、用户洞察三路并行，以及供应商和财务两路并行，减少没有业务依赖的串行等待。
4. 实现节点级重试和指数退避。某个节点失败时优先重试当前节点，而不是重复执行整条工作流。
5. 每个节点记录 `started`、`retrying`、`completed`、`skipped`、`failed` 等事件、尝试次数、错误信息和输出复用情况。
6. 运行状态覆盖 `queued`、`running`、`approval_required`、`completed`、`failed`、`cancelled` 和 `superseded`，项目状态与运行状态分别维护。
7. 通过项目行锁和活动运行检查防止同一项目并发启动多个运行；进行中或待审批的项目不允许修改规划参数。
8. 规划参数、规划指标快照、Agent 输出、证据引用、评分结果和最终报告均保存运行级输入/结果快照，保证运行可复现。

#### 3. 业务节点开发与职责边界

> LLM Agent 负责业务编排、工具调用、结构化推理和文本生成；确定性工具负责关键数值和事实查询；最终状态变更下沉到业务 API，禁止让 LLM 直接决定经营事实。

1. **Requirement Agent**

   - 将自然语言或表单输入转换为结构化品类、市场、目标用户、价格范围、目标毛利、供应商和交期约束。
   - 对输入进行规范化，形成后续 Agent 共用的规划上下文。

2. **Market 检索工具**

   - 查询市场趋势、价格、销量、库存和品类指标。
   - 使用租户、品类和目标市场过滤检索证据。
   - 输出市场机会、趋势判断、证据引用和数据覆盖情况。

3. **Competitor 检索工具**

   - 识别竞品、价格、功能、评价和差异化特征。
   - 输出竞品对比、竞争风险和可形成差异化的商品方向。

4. **User Insight 检索工具**

   - 处理用户评价和反馈中的痛点、场景、需求标签和负面体验。
   - 将短评价结合商品、渠道、品类和标题上下文后再进入检索，提升证据语义完整性。

5. **Concept Agent**

   - 综合市场、竞品、用户洞察和规划指标，生成 3 个结构化候选商品概念。
   - 每个候选包含定位、目标用户、证据特征、痛点、功能假设、价格/成本参考、差异化假设、验证风险和四道验证门。
   - 对候选概念生成独立评分，支持审批人员通过候选 ID 选择最终方向。

6. **Supplier 评估工具**

   - 检查供应商信息完整性、MOQ、交期、可接受交期和供应风险。
   - 对缺失的供应商输入给出候选推荐，但不绕过人工供应验证。

7. **Finance 财务测算引擎**

   - 使用 Decimal 和规则服务计算售价、成本、平台/物流/税费/营销费用、毛利、毛利率、收入、预计利润和盈亏平衡销量。
   - 明确项目约束优先，候选概念价格/成本只用于补充缺失值。

8. **Scoring 机会评分引擎**

   - 综合证据适配度、商业可行性、供应风险和数据准备度等维度。
   - 输出 100 分机会评分、评分拆解、风险说明和优先验证建议。

9. **Narrative Agent**

   - 将结构化证据、财务、供应和评分结果转换成管理层摘要、推荐理由、风险清单和下一步行动。
   - 不修改 PostgreSQL 业务事实，也不直接改变审批或上市状态。

10. **review_agent 人工审批门禁**

   - 把运行状态设置为 `approval_required`，创建系统内审批任务。
   - 它不是自动审批 Agent，不会自动通过、驳回或确认上市。
   - 审批人员在线决定后，Worker 根据审批结果完成、取消或创建修订运行。

#### 4. 异步执行、记忆与状态持久化

1. **Celery 任务编排**

   - `execute_planning_run`：执行规划 Agent 主流程。
   - `resume_planning_run`：审批通过或要求修订后恢复流程。
   - `process_tabular_import`：异步解析和治理 Excel/CSV。
   - `generate_embedding_index`、`index_evidence_batch`：生成和写入证据向量。
   - `generate_planning_report`：异步生成 XLSX 报告。

2. **Redis 短期状态**

   - 作为 Celery Broker 和结果后端。
   - 保存 Agent 执行中的 Checkpoint、Redis Stream 事件、分布式锁和短期协作状态。
   - WebSocket 主要推送增量事件，刷新后通过事件历史和 PostgreSQL 快照恢复页面。

3. **PostgreSQL 最终事实**

   - 保存项目、运行、审批、选品、立项、验证材料元数据、试销记录、报告任务和审计事件。
   - Redis 事件丢失时，仍可以通过 PostgreSQL 运行快照查看最终状态和部分中间结果。

4. **可恢复执行**

   - 失败节点达到重试上限后，运行状态记为 `failed`，保留部分输出和错误信息。
   - 规划人员恢复同一运行时，已完成节点通过 `resume_completed_nodes` 跳过并复用持久化输出，避免重复调用模型和检索服务。
   - 审批等待期间保留运行上下文和 Checkpoint；审批通过后继续恢复，要求修订时生成带父子关系的新运行。

#### 5. 业务闭环与人机协同

1. **系统内线上规划审批**

   - Agent 完成分析后创建审批任务。
   - 审批人员可以查看候选方案、证据、财务测算、供应风险、评分和验证计划。
   - 支持在线通过、驳回和要求修订。
   - 审批提交使用 `Idempotency-Key`，网络重试不会重复处理同一决定。
   - 审批任务支持认领、释放、转派和 SLA 标识，避免多人同时处理同一任务。

2. **正式选品与验证**

   - 审批通过后自动生成 `selected_products` 正式选品台账。
   - 台账保存最终候选、财务指标、供应状态、验证状态、负责人和审批快照。
   - 支持需求匹配、规格样品、商业可行和供应交付四道验证门。
   - 验证门标记为 ready 前必须有有效人工材料，材料元数据进入运行快照，文件由对象存储适配器管理。
   - 规划人员可以维护推进状态、负责人、暂停、终止和备注，但不能覆盖原始审批和运行快照。

3. **商品立项、试销和上市评审**

   - 验证 ready 的正式选品可以创建唯一商品立项。
   - 每个立项包含项目启动、样品定版、成本定版、小批量试销和上市准备评审五个里程碑。
   - 试销记录按租户、立项、报告周期和渠道保持唯一，系统计算转化率、退货率、客单价、实际毛利、实际毛利率、营销 ROI 和平均评分。
   - 上市准备预检返回 `ready`、`review` 或 `blocked`，但不会自动改变上市状态。
   - 规划人员提交上市评审，审批人员在线决定 `approved`、`revision_required` 或 `rejected`，最终确认上市仍然保留人工责任。

4. **人机协同原则**

   - Agent 负责整理证据、分析和建议，业务人员负责审批、验证材料和最终上市决定。
   - 系统不把人工审批伪装成自动 Agent，而是把人工决策建模为可暂停、可恢复、可审计的工作流门禁。
   - 每次人工操作记录操作者、时间、业务对象、前后状态、备注和请求来源。

#### 6. FastMCP 能力开放与统一工具边界

1. 使用 FastMCP 4.0.1 建立独立 MCP 服务，当前提供 11 个只读工具和 6 个受控写入工具。
2. 只读工具覆盖规划项目、规划运行、证据检索、审批任务、正式选品、商品立项、上市评审上下文、项目全链路和业务驾驶舱。
3. 受控写入工具覆盖规划草稿创建、确认启动 Agent、验证门更新、上市评审提交、审批任务认领和审批决定提交。
4. MCP 服务通过 `MerchPilotTokenVerifier` 解析身份，并按 `admin`、`planner`、`approver` 和 `viewer` 角色暴露不同工具。
5. 所有列表工具使用服务端分页，限制最大 `page_size`，避免外部 Agent 一次读取过量业务数据。
6. 受控写入要求复核令牌、明确确认词和请求 ID；写入操作绑定租户、操作者、操作名称和幂等键。
7. FastMCP 不直连 PostgreSQL、Redis 或 Milvus，统一通过既有 FastAPI 接口复用租户隔离、状态校验、业务门禁和审计。
8. Agent 集成页面提供 MCP 健康检查、身份协议验证、工具目录、客户端配置复制和真实业务验证。

#### 7. 质量、可靠性与审计

1. **租户与角色隔离**：所有项目、运行、证据、审批、选品、立项、报告和审计接口由服务端按 `tenant_id` 过滤，不接受客户端覆盖租户。
2. **状态一致性**：项目、运行和审批行使用锁与状态检查；过期审批、重复启动和非法状态变更会被拒绝。
3. **幂等控制**：审批决定、MCP 草稿创建、MCP 启动、上市评审和试销记录使用幂等键或数据库唯一约束，防止网络重试和并发写入产生重复业务事实。
4. **失败恢复**：节点级指数退避、失败快照、已完成节点复用、Redis Checkpoint 和 PostgreSQL 快照共同支持恢复执行。
5. **审计追溯**：项目、运行、审批、导入、选品、验证、立项、试销、MCP 操作全部进入 PostgreSQL 审计流；同一时间的并发事件通过数据库序号保证确定性排序。
6. **服务端分页**：项目、运行、证据、审批、导入、选品、立项、审计和 MCP 活动均采用服务端分页，避免前端全量加载。
7. **报告安全**：XLSX 报告由 pandas/openpyxl 生成，导入或模型输出的文本写入 Excel 前进行公式注入防护。
8. **测试覆盖**：覆盖 Agent 图、检索治理、导入质量、财务和供应规则、身份权限、项目生命周期、审批、MCP、报告、存储、Worker 状态和 PostgreSQL 集成场景。

#### 8. 配套测试工作

1. **单元测试**：验证财务、供应、评分、候选概念、导入模板、检索治理、审批门禁、项目状态和存储适配器。
2. **Agent 流程测试**：验证 13 个规划节点、LLM Prompt 契约、确定性守门、并行边、节点重试、输出复用、人工审批状态和失败快照。
3. **权限测试**：验证 viewer、planner、approver 和 admin 对业务模块、审批操作、审计和 MCP 工具目录的差异。
4. **租户隔离测试**：验证项目、运行、证据、审批、导入、分析、报告、审计和 MCP 请求不能读取其他租户数据。
5. **幂等与并发测试**：验证审批重复提交、MCP 请求重放、项目并发启动、试销唯一约束和上市评审重复提交。
6. **集成测试**：使用隔离的 `merchpilot_test` 数据库验证 PostgreSQL 事务和完整 API 业务边界。
7. **本地闭环验收**：通过 `scripts/validate-local.sh` 检查 API、PostgreSQL、Redis、Milvus、Celery、FastMCP、身份、对象存储、规划、审批、选品、立项和 Web 页面。

### 技术栈：

| 技术层 | 主要技术 | 在项目中的作用 |
| --- | --- | --- |
| 前端框架 | React 19、Next.js 16、TypeScript | 构建企业业务工作台和模块化页面 |
| UI 与交互 | Ant Design、Ant Design Icons | 表单、表格、审批、分页、弹窗和角色化交互 |
| 前端状态 | Redux Toolkit | 身份、运行进度、当前项目上下文和快照恢复 |
| 前端请求 | Axios 自行封装 | 统一认证头、错误处理、分页参数和业务 API 类型 |
| 图表与流程 | AntV Charts、AntV X6 | 机会评分图表和 Agent Mesh 流程展示 |
| 实时通信 | WebSocket、Redis Stream | Agent 节点进度增量推送和历史事件恢复 |
| 后端框架 | FastAPI、Pydantic、SQLAlchemy Async | REST API、Schema 校验、异步数据库访问和依赖注入 |
| 工作流编排 | LangGraph、StateGraph | LLM Agent、确定性工具、并行分支、重试和人工审批门禁 |
| 异步任务 | Celery、Redis | 长耗时导入、Embedding、Agent 运行、索引和报告任务 |
| 业务数据库 | PostgreSQL 16、Alembic | 业务事实、状态、快照、审批、审计和唯一约束 |
| 向量数据库 | Milvus 3.0 | 证据向量索引和语义召回 |
| 检索模型 | BGE-M3、BGE Reranker | Embedding、证据召回和候选重排 |
| 大模型 | DashScope Qwen 兼容接口 | 文本理解、建议生成和规划叙事，关键数值由规则计算 |
| 数据处理 | pandas、openpyxl、XLSX | 表格导入、质量治理、报告生成和 Excel 安全处理 |
| MCP | FastMCP 4.0.1 | 向外部 Agent 开放受控业务工具 |
| 文件存储 | Docker 本地文件卷、ObjectStorageProvider | 原始导入文件、验证材料和报告文件存储 |
| 认证 | Local Identity、IdentityProvider | 本地角色切换和未来企业 SSO/OIDC 替换点 |
| 审批集成 | Internal Approval、ExternalApprovalProvider | 当前系统内审批和未来 OA 同步扩展 |
| 部署 | Docker Compose | 本地 Web、API、Worker、MCP、PostgreSQL、Redis、Milvus 和模型服务编排 |
| 质量保障 | pytest、Ruff、TypeScript、Next Build | 单元测试、集成测试、代码检查和前端构建验证 |
