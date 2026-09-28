"""流式 Agent 的人工审批闸门（Human-in-the-Loop）。"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field


def _timeout_seconds() -> int:
    try:
        return max(30, min(int(os.getenv("HITL_TIMEOUT_SECONDS", "300")), 3600))
    except ValueError:
        return 300


def enabled() -> bool:
    return os.getenv("HITL_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class PendingApproval:
    id: str
    thread_id: str
    tool: str
    args: dict
    description: str
    created_at: float = field(default_factory=time.monotonic)
    event: threading.Event = field(default_factory=threading.Event)
    decision: dict | None = None


class ApprovalManager:
    """进程内审批协调器；审批等待期间不会执行受保护的工具。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[str, PendingApproval] = {}

    def create(self, thread_id: str, tool: str, args: dict, description: str) -> PendingApproval:
        request = PendingApproval(uuid.uuid4().hex, thread_id, tool, dict(args or {}), description)
        with self._lock:
            self._pending[request.id] = request
        return request

    def wait(self, request: PendingApproval) -> dict:
        request.event.wait(_timeout_seconds())
        with self._lock:
            self._pending.pop(request.id, None)
        return request.decision or {"decision": "timeout", "message": "审批超时，受保护操作未执行。"}

    def resolve(self, approval_id: str, decision: str, message: str = "", args: dict | None = None) -> dict | None:
        decision = str(decision or "").strip().lower()
        if decision not in {"approve", "reject", "edit"}:
            raise ValueError("decision 只能是 approve、reject 或 edit")
        with self._lock:
            request = self._pending.get(approval_id)
            if request is None or request.event.is_set():
                return None
            if decision == "edit" and not isinstance(args, dict):
                raise ValueError("编辑审批必须提供 args 对象")
            request.decision = {"decision": decision, "message": str(message or "").strip(), "args": dict(args or {})}
            request.event.set()
            return {"id": request.id, "thread_id": request.thread_id, "tool": request.tool, "decision": decision}

    def summary(self) -> dict:
        with self._lock:
            pending = len(self._pending)
        return {"enabled": enabled(), "protected_tools": ["forget"], "timeout_seconds": _timeout_seconds(), "pending": pending}


manager = ApprovalManager()


def requires_approval(tool_name: str) -> bool:
    return enabled() and tool_name == "forget"
