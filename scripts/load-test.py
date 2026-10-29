"""对本地 API 执行可控的异步并发基准测试。"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class Sample:
    latency_ms: float
    status_code: int
    error: str | None = None


async def run_load_test(url: str, total: int, concurrency: int, token: str | None) -> list[Sample]:
    """并发请求指定接口并收集每次请求的耗时和状态。"""
    semaphore = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = httpx.Timeout(10.0, connect=3.0)

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        async def request_once() -> Sample:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    return Sample(
                        latency_ms=(time.perf_counter() - started) * 1000,
                        status_code=response.status_code,
                    )
                except Exception as exc:
                    return Sample(
                        latency_ms=(time.perf_counter() - started) * 1000,
                        status_code=0,
                        error=type(exc).__name__,
                    )

        return await asyncio.gather(*(request_once() for _ in range(total)))


def percentile(values: list[float], ratio: float) -> float:
    """返回线性插值百分位，避免依赖额外压测工具。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_args() -> argparse.Namespace:
    """解析压测参数。"""
    parser = argparse.ArgumentParser(description="MerchPilot API load test")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health/live")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--token", default=None)
    return parser.parse_args()


async def main() -> None:
    """执行压测并输出吞吐、错误率和延迟分位数。"""
    args = parse_args()
    started = time.perf_counter()
    samples = await run_load_test(args.url, args.requests, args.concurrency, args.token)
    elapsed = time.perf_counter() - started
    latencies = [sample.latency_ms for sample in samples]
    successful = sum(200 <= sample.status_code < 400 for sample in samples)
    errors = [sample for sample in samples if sample.error or not 200 <= sample.status_code < 400]
    print(f"url={args.url}")
    print(f"requests={len(samples)} concurrency={args.concurrency} elapsed_s={elapsed:.3f}")
    print(f"throughput_rps={len(samples) / elapsed:.2f} success={successful} failures={len(errors)}")
    print(
        "latency_ms="
        f"p50:{percentile(latencies, 0.50):.2f} "
        f"p95:{percentile(latencies, 0.95):.2f} "
        f"p99:{percentile(latencies, 0.99):.2f} "
        f"max:{max(latencies, default=0):.2f}"
    )
    if errors:
        print(f"failure_statuses={sorted({sample.status_code for sample in errors})}")


if __name__ == "__main__":
    asyncio.run(main())
