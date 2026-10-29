# 品策智选 MerchPilot｜面试材料入口

> 当前版本：2026 年 9 月 8 日

本文件保留为旧路径兼容入口。项目经过多轮迭代后，面试材料已拆分为三份，避免把项目介绍、简历和追问答案混在一起。

## 当前推荐阅读顺序

1. `docs/面试项目逐字稿_2026版.md`
   - 3分钟项目介绍
   - 完整业务闭环
   - 当前技术栈
   - Agent节点职责
   - 个人主责和演示顺序
2. `docs/简历项目经历_2026版.md`
   - 简历3条精简版
   - 简历5条标准版
   - 后端/AI岗位版
   - 全栈/平台岗位版
   - 简历表述红线
3. `docs/面试问答与表述边界_2026版.md`
   - RAG与数据库追问
   - LangGraph与Agent拆分
   - Celery、Redis与恢复机制
   - 人工审批、多租户和性能
   - SSO、OA、OSS与FastMCP边界

## 当前统一口径

- 业务方向：零售商品企划与智能选品。
- 规划 Mesh：13 个节点，由 5 个 LLM Agent、7 个确定性业务工具和 1 个人工审批门禁组成。
- 导入链路：另有1个多模态证据抽取Agent，不计入规划Mesh。
- 业务事实：PostgreSQL。
- 语义检索：Milvus + BGE-M3 + BGE Reranker。
- 长任务与过程状态：Celery + Redis。
- 后端：FastAPI + SQLAlchemy 2 + Pydantic + Alembic。
- 前端：React + Next.js + Redux Toolkit + Ant Design + AntV + Axios + WebSocket。
- 能力开放：FastMCP，复用身份、租户、权限、幂等和审计规则。
- 部署：Docker Compose，本地包含API、Worker、Web、FastMCP、PostgreSQL、Redis、Milvus、模型服务和Prometheus等组件。
- 企业SSO、外部OA、阿里云OSS和生产监控：当前保留Provider扩展接口，不表述为已经正式接入生产。

## 旧材料处理说明

旧版内容中的技术方向和业务背景仍可作为历史参考，但不要继续直接背诵。尤其不要沿用“9个Agent全部由大模型驱动”或旧版FastMCP工具数量等表述；当前实现采用模型节点、确定性工具和人工门禁的混合架构。
