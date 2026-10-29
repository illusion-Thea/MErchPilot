# 性能与高并发方案

## 当前实现

- PostgreSQL 使用异步连接池：`pool_size=20`、`max_overflow=30`、连接预检查和回收；参数通过环境变量调整。
- API 使用 Uvicorn 多进程，默认 `2` 个进程；HTTP 请求、状态码和延迟通过 Prometheus 暴露。
- Redis Lua 脚本实现用户级和租户级原子限流，默认每用户每分钟 `600` 次、每租户 `5000` 次。
- Celery 按职责拆分为规划/Agent、索引、报告三个 Worker，可分别调整并发数和副本数。
- Redis 分布式锁保护项目启动、规划运行和 Agent 节点。裸 `Settings` 默认关闭，当前 Docker Compose 与 `.env.example` 默认开启；Redis 暂时不可用时按 `DISTRIBUTED_LOCK_FAIL_OPEN` 策略处理。
- 模型服务增加舱壁并发、排队超时和熔断；embedding 与 reranker 服务各自独立扩容。
- PostgreSQL 慢查询和 Celery 队列深度通过 `/metrics` 与 Prometheus 采集。
- 模型客户端在同一事件循环复用 HTTP 连接池，Celery 新建事件循环时自动重建，避免连接跨 loop 使用。

## 并发请求链路

1. FastAPI 完成身份认证，并通过 Redis Lua 按用户和租户执行原子限流。
2. 启动规划时通过项目锁、活动 Run 检查、唯一约束和可选 `Idempotency-Key` 防止重复业务动作。
3. API 在 PostgreSQL 短事务中保存 Run、项目状态、审计和幂等账本，提交后立即返回 `202`。
4. Agent、索引和报告进入不同 Celery 队列；`acks_late=true`、`worker_prefetch_multiplier=1` 避免慢任务被单个 Worker 大量预取。
5. LangGraph 只并行无依赖步骤：市场/竞品/用户研究三路并行，供应链/财务两路并行。
6. 模型调用受进程内 Semaphore、排队超时和熔断器保护；Embedding 采用批量请求，Milvus 写入不占用 HTTP 请求。
7. Worker 将增量事件写入 Redis Stream，WebSocket 使用阻塞 `XREAD` 推送，避免高频轮询 PostgreSQL。

## 容量预算

- 数据库连接不能只看 `DATABASE_POOL_SIZE=20`。每个 API/Worker 进程及每个副本都有独立连接池，理论上界应按所有进程的 `pool_size + max_overflow` 求和，并为迁移、运维和故障切换预留连接。
- Worker 吞吐近似为“并发数 ÷ 单任务平均耗时”。规划、索引、报告的瓶颈不同，必须按队列分别看任务耗时和积压。
- 当前模型舱壁是进程内保护。多个服务副本共享同一远端模型容量时，还需要在模型网关或 Redis 层做集群级配额。
- 整体吞吐由最慢的受限资源决定，通常是 LLM/Embedding、数据库连接或 Celery 消费能力，而不是 FastAPI 路由本身。

## 当前边界

- `scripts/load-test.py` 已能输出 GET 请求的吞吐、p50、p95、p99 和失败数，但尚未覆盖启动规划、Celery、LLM、Milvus、WebSocket 与审批恢复的混合负载，因此不能据此宣称已达到生产级高并发目标。
- Web 端 `startProjectRun` 当前未发送 `Idempotency-Key`。后端项目锁和活动 Run 检查能拦截多数重复启动，但还没有形成完整的客户端结果重放语义。
- Celery 任务通过 `asyncio.run` 建立事件循环，并在任务后释放数据库、Redis 和模型客户端，隔离性较好，但高吞吐下会损失连接复用效率。
- 本地 Docker Compose 使用单实例 PostgreSQL 和 Redis，解决的是可运行闭环，不是生产高可用；生产还需 PgBouncer、托管高可用、备份恢复、容量告警和故障演练。

## 本地验证

```bash
# 启动完整链路
 docker compose up -d --build

# 查看就绪状态
 ./scripts/validate-local.sh

# 对健康接口做基准测试
 backend/.venv/bin/python scripts/load-test.py --requests 100 --concurrency 10

# 通过 Prometheus 查看指标
 curl http://127.0.0.1:8000/metrics
```

建议先对 `/health/live` 测网络和 API 进程，再对 `/api/v1/planning-projects/page?page=1&page_size=10` 测数据库和限流。压测业务接口时保持请求量低于当前限流窗口，或临时调整 `.env` 中的 `RATE_LIMIT_REQUESTS`。

## 调参原则

- API：CPU 密集型场景优先增加副本；I/O 密集型场景先观察数据库连接池占用和 p95。
- 规划 Worker：受 LLM、Redis 事件和数据库影响，优先横向扩容，不盲目提高单容器并发。
- 索引 Worker：受 embedding、Milvus 和磁盘吞吐影响，先调 `INDEX_WORKER_CONCURRENCY`，再增加副本。
- 模型服务：`MODEL_SERVICE_MAX_CONCURRENCY` 不应超过模型实例实际吞吐；排队超时用于快速失败，避免请求堆积拖垮实例。
- PostgreSQL：连接池总连接数应小于数据库 `max_connections`，多副本部署时按实例数平摊。
- Redis：限流、锁、Celery Broker 和状态缓存分库隔离；生产环境建议把 Redis 高可用和持久化交给基础设施平台。

## 上线前压测清单

- 场景：只读列表、启动规划、批量导入、向量索引、WebSocket 长连接、审批恢复按真实比例混合。
- 指标：吞吐、p50/p95/p99、错误率、限流拒绝、队列等待、任务耗时、数据库连接、慢 SQL、模型舱壁拒绝、CPU、内存和网络。
- 方法：逐级增加并发直到出现延迟拐点或错误率上升，再定位最先饱和的资源并单点调优。
- 验收：为关键接口定义 SLO，并用容量余量而不是峰值极限作为生产并发配置。
