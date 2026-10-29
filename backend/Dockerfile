# 文件职责：构建轻量、非 root 的 FastAPI/Celery 通用后端运行镜像。

FROM python:3.12-slim AS runtime

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_DEFAULT_TIMEOUT=180

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# 运行进程使用普通用户；上传文件目录提前授权，避免容器内以 root 写业务文件。
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data/files \
    && chown -R app:app /app /data

COPY pyproject.toml README.md ./

# 先安装依赖再复制源码，业务代码变化时可以复用 Docker 依赖层缓存。
RUN mkdir -p src \
    && pip install \
    --no-cache-dir \
    --retries 10 \
    --timeout "$PIP_DEFAULT_TIMEOUT" \
    --index-url "$PIP_INDEX_URL" \
    .

# API 与 Worker 共用源码和 Alembic 迁移定义。
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

USER app

EXPOSE 8000

CMD ["uvicorn", "merchpilot.main:app", "--host", "0.0.0.0", "--port", "8000"]
