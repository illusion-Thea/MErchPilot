"""文件职责：加载本地 Embedding/Reranker 模型并执行批量推理。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from merchpilot.core.config import get_settings


class TransformerReranker:
    """`TransformerReranker` 封装本模块相关状态和行为，对调用方提供清晰边界。"""
    def __init__(
        self,
        model_path: Path,
        *,
        device: str,
        batch_size: int,
        max_length: int,
    ) -> None:
        """初始化`TransformerReranker`所需依赖和默认状态。"""
        from transformers import AutoModelForSequenceClassification

        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.tokenizer = _load_reranker_tokenizer(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_path),
            local_files_only=True,
            dtype=resolve_model_dtype(device),
        )
        self.model.to(device)
        self.model.eval()

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """实现`predict`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        import torch

        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            queries = [query for query, _ in batch]
            documents = [document for _, document in batch]
            inputs = self.tokenizer(
                queries,
                documents,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)
            with torch.inference_mode():
                logits = self.model(**inputs, return_dict=True).logits
            scores.extend(float(score) for score in logits.detach().float().cpu().view(-1).tolist())
        return scores


def _load_reranker_tokenizer(model_path: Path) -> Any:
    """内部辅助函数`_load_reranker_tokenizer`；拆分主流程并集中处理当前模块的边界条件。"""
    from transformers import AutoTokenizer, XLMRobertaTokenizer

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=True,
            use_fast=False,
        )
        if callable(tokenizer):
            return tokenizer
    except Exception:
        pass

    for filename in ("sentencepiece.bpe.model", "tokenizer.model"):
        vocab_path = model_path / filename
        if vocab_path.exists():
            return XLMRobertaTokenizer(vocab_file=str(vocab_path))
    raise RuntimeError(f"reranker tokenizer could not be loaded from: {model_path}")


def resolve_device() -> str:
    """实现`resolve_device`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    settings = get_settings()
    if settings.model_device != "auto":
        return settings.model_device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ModuleNotFoundError:
        return "cpu"


def resolve_model_dtype(device: str) -> Any:
    """选择兼顾设备兼容性和本地内存峰值的模型权重精度。"""
    import torch

    configured = get_settings().model_dtype
    if configured == "auto":
        configured = "float16" if device.startswith("cuda") else "bfloat16"
    return {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }[configured]


def configure_torch_runtime(device: str) -> None:
    """限制本地 CPU 推理线程，降低大模型首次加载和并行计算的内存峰值。"""
    if device != "cpu":
        return
    import torch

    threads = get_settings().model_cpu_threads
    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(max(1, min(threads, 2)))
    except RuntimeError:
        # PyTorch 只允许在并行工作开始前设置一次；缓存模型复用时保持已有值。
        pass


def _require_path(path: Path, label: str) -> None:
    """内部辅助函数`_require_path`；拆分主流程并集中处理当前模块的边界条件。"""
    if not path.exists():
        raise RuntimeError(f"{label} path does not exist: {path}")


@lru_cache(maxsize=1)
def get_embedding_model() -> Any:
    """实现`get_embedding_model`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    from langchain_huggingface import HuggingFaceEmbeddings

    settings = get_settings()
    _require_path(settings.embedding_model_path, "embedding model")
    device = resolve_device()
    configure_torch_runtime(device)
    embeddings = HuggingFaceEmbeddings(
        model_name=str(settings.embedding_model_path),
        model_kwargs={
            "device": device,
            "local_files_only": True,
            "model_kwargs": {"dtype": resolve_model_dtype(device)},
        },
        encode_kwargs={
            "batch_size": settings.embedding_inference_batch_size,
            "normalize_embeddings": True,
        },
    )
    embeddings._client.max_seq_length = settings.embedding_max_length
    return embeddings


@lru_cache(maxsize=1)
def get_reranker_model() -> Any:
    """实现`get_reranker_model`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    settings = get_settings()
    _require_path(settings.reranker_model_path, "reranker model")
    device = resolve_device()
    configure_torch_runtime(device)
    return TransformerReranker(
        settings.reranker_model_path,
        device=device,
        batch_size=settings.reranker_batch_size,
        max_length=settings.reranker_max_length,
    )
