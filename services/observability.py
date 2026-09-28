"""LangSmith 可观测性配置摘要。

LangChain / LangGraph 会自动读取 LANGSMITH_* 环境变量创建追踪，不需要在每个
模型或工具调用点重复注入回调。本模块只负责把当前有效配置安全地暴露给健康检查。
"""
from __future__ import annotations

import os
from importlib.util import find_spec


def _enabled() -> bool:
    value = (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or "").strip().lower()
    return value == "true"


def _sampling_rate() -> tuple[float | None, str | None]:
    raw = (os.getenv("LANGSMITH_TRACING_SAMPLING_RATE") or
           os.getenv("LANGCHAIN_TRACING_SAMPLING_RATE") or "").strip()
    if not raw:
        return None, None
    try:
        rate = float(raw)
    except ValueError:
        return None, "采样率必须是 0 到 1 之间的数字"
    if not 0 <= rate <= 1:
        return None, "采样率必须在 0 到 1 之间"
    return rate, None


def langsmith_summary() -> dict:
    """返回非敏感 LangSmith 配置；绝不返回 API Key。"""
    sampling_rate, error = _sampling_rate()
    api_key_configured = bool((os.getenv("LANGSMITH_API_KEY") or
                               os.getenv("LANGCHAIN_API_KEY") or "").strip())
    return {
        "enabled": _enabled(),
        "package_available": find_spec("langsmith") is not None,
        "api_key_configured": api_key_configured,
        "project": (os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "default").strip(),
        "sampling_rate": sampling_rate,
        "warning": error or (
            "追踪已开启，但尚未配置 LANGSMITH_API_KEY" if _enabled() and not api_key_configured else None
        ),
    }
