"""文件职责：把本地 PyTorch 模型转换为低内存 BF16 safetensors 分片副本。"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import save_file

WEIGHT_FILENAMES = {
    "model.safetensors",
    "model.safetensors.index.json",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
}


def parse_size(value: str) -> int:
    """把 GB/MB/KB 字符串转换为字节数。"""
    normalized = value.strip().upper()
    units = {"GB": 1024**3, "MB": 1024**2, "KB": 1024}
    for suffix, multiplier in units.items():
        if normalized.endswith(suffix):
            return int(float(normalized.removesuffix(suffix)) * multiplier)
    return int(normalized)


def copy_model_metadata(source: Path, destination: Path) -> None:
    """复制配置、分词器和 SentenceTransformers 模块文件，排除旧权重。"""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in WEIGHT_FILENAMES or item.name.startswith("model-"):
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def reset_destination(destination: Path) -> None:
    """清空输出内容但保留 Docker 挂载点本身，兼容 Makefile 直接挂载目标目录。"""
    destination.mkdir(parents=True, exist_ok=True)
    for item in destination.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def plan_shards(
    state_dict: dict[str, torch.Tensor],
    max_shard_bytes: int,
) -> list[list[str]]:
    """只按目标 BF16 大小规划分片，不提前复制任何大张量。"""
    shards: list[list[str]] = []
    shard: list[str] = []
    shard_bytes = 0
    for name, tensor in state_dict.items():
        converted_bytes = tensor.numel() * torch.bfloat16.itemsize
        if shard and shard_bytes + converted_bytes > max_shard_bytes:
            shards.append(shard)
            shard = []
            shard_bytes = 0
        shard.append(name)
        shard_bytes += converted_bytes
    if shard:
        shards.append(shard)
    return shards


def convert_shard(
    state_dict: dict[str, torch.Tensor],
    names: Sequence[str],
) -> dict[str, torch.Tensor]:
    """只转换当前分片需要的张量，写盘后即可释放内存。"""
    return {
        name: state_dict[name].to(dtype=torch.bfloat16).contiguous()
        for name in names
    }


def update_config(destination: Path) -> None:
    """把副本配置标记为 BF16，便于运行时和诊断接口识别。"""
    config_path = destination / "config.json"
    if not config_path.exists():
        return
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["torch_dtype"] = "bfloat16"
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def convert_model(source: Path, destination: Path, max_shard_bytes: int) -> None:
    """读取内存映射权重并生成 Transformers 可直接加载的安全分片索引。"""
    source_weights = source / "pytorch_model.bin"
    if not source_weights.exists():
        raise FileNotFoundError(f"未找到模型权重：{source_weights}")
    reset_destination(destination)
    copy_model_metadata(source, destination)
    update_config(destination)

    state_dict = torch.load(
        source_weights,
        map_location="cpu",
        weights_only=True,
        mmap=True,
    )
    if not isinstance(state_dict, dict):
        raise TypeError("模型权重不是预期的 state_dict")

    shard_plan = plan_shards(state_dict, max_shard_bytes)
    shard_total = len(shard_plan)
    weight_map: dict[str, str] = {}
    total_size = 0
    for index, names in enumerate(shard_plan, start=1):
        filename = f"model-{index:05d}-of-{shard_total:05d}.safetensors"
        shard = convert_shard(state_dict, names)
        save_file(shard, destination / filename, metadata={"format": "pt"})
        for name, tensor in shard.items():
            weight_map[name] = filename
            total_size += tensor.numel() * tensor.element_size()
        del shard

    index_payload: dict[str, Any] = {
        "metadata": {"total_size": total_size},
        "weight_map": weight_map,
    }
    (destination / "model.safetensors.index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source": str(source),
                "destination": str(destination),
                "shards": shard_total,
                "weights": len(weight_map),
                "size_gib": round(total_size / 1024**3, 3),
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    """解析命令行参数并执行单个模型转换。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--max-shard-size", default="600MB")
    arguments = parser.parse_args()
    convert_model(
        arguments.source,
        arguments.destination,
        parse_size(arguments.max_shard_size),
    )


if __name__ == "__main__":
    main()
