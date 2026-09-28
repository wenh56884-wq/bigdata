"""LangChain Agent 的统一错误处理与调试配置。"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from services import sanitize

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def enabled() -> bool:
    value = (os.getenv("DEBUG_MODE") or os.getenv("LANGCHAIN_VERBOSE") or "").strip().lower()
    return value in {"1", "true", "yes", "on", "debug"}


def level() -> str:
    value = (os.getenv("LOG_LEVEL") or ("DEBUG" if enabled() else "INFO")).strip().upper()
    return value if value in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"


def log_path() -> Path | None:
    configured = (os.getenv("LOG_FILE") or "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging() -> logging.Logger:
    """配置一次应用日志；不改变调用方已有 handlers。"""
    logger = logging.getLogger("jiutian.agent")
    logger.setLevel(getattr(logging, level()))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        path = log_path()
        if path:
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setFormatter(handler.formatter)
            logger.addHandler(file_handler)
    return logger


LOGGER = configure_logging()


def error_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_message(exc: BaseException) -> str:
    """异常信息脱敏后再返回给前端或写入日志。"""
    text = sanitize.mask_text(str(exc).strip())
    return text[:1000] or type(exc).__name__


def record_error(exc: BaseException, *, error_id_value: str | None = None, context: str = "") -> str:
    identifier = error_id_value or error_id()
    detail = safe_message(exc)
    LOGGER.error("agent_error id=%s context=%s type=%s message=%s", identifier, context, type(exc).__name__, detail, exc_info=enabled())
    return identifier


def error_payload(exc: BaseException, *, error_id_value: str | None = None, context: str = "") -> dict:
    identifier = record_error(exc, error_id_value=error_id_value, context=context)
    payload = {"error": "服务处理失败，请稍后重试。", "error_id": identifier}
    if enabled():
        payload["detail"] = safe_message(exc)
    return payload


def summary() -> dict:
    path = log_path()
    return {
        "enabled": enabled(),
        "level": level(),
        "langchain_verbose": (os.getenv("LANGCHAIN_VERBOSE") or "").strip().lower() == "true",
        "log_file": str(path) if path else None,
        "stack_traces_in_response": enabled(),
    }
