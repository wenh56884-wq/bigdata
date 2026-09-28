"""自动学习资料：把上传表格摘要和已完成问答写进本地 RAG 知识库。"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from services import sanitize

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()
_MAX_DAILY_FILE_BYTES = 5 * 1024 * 1024


def _directory() -> Path:
    """自动学习资料目录；可用 AUTO_KNOWLEDGE_DIR 单独指定。"""
    configured = (os.getenv("AUTO_KNOWLEDGE_DIR") or "").strip()
    base = Path(configured) if configured else PROJECT_ROOT / "knowledge" / "自动学习"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_file_name(name: str) -> str:
    return "".join("_" if ch in '\\/:*?\"<>|' else ch for ch in str(name)).strip(" .") or "未命名资料"


def _table_path(file_name: str) -> Path:
    return _directory() / "上传表格" / f"{_safe_file_name(file_name)}.md"


def _qa_path(now: datetime) -> Path:
    directory = _directory() / "问答记录"
    directory.mkdir(parents=True, exist_ok=True)
    stem = now.strftime("%Y-%m-%d")
    path = directory / f"{stem}.md"
    index = 2
    while path.exists() and path.stat().st_size >= _MAX_DAILY_FILE_BYTES:
        path = directory / f"{stem}_{index}.md"
        index += 1
    return path


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT / "knowledge")).replace("\\", "/")
    except ValueError:
        return str(path)


def remember_table_upload(file_name: str, cards: list[dict]) -> str:
    """为上传表格写入结构摘要，让资料检索也能识别列、样例和枚举值。"""
    lines = [f"# 上传表格：{file_name}", "", f"更新时间：{datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    for card in cards:
        lines.append(
            f"## {card.get('source_id') or file_name}"
            f"（{card.get('n_rows', 0)} 行 × {card.get('n_cols', 0)} 列）"
        )
        for field in card.get("columns") or []:
            name = str(field.get("name") or "未命名列")
            sample = [str(value) for value in field.get("sample") or []]
            values = [str(value) for value in field.get("values") or []]
            detail = f"类型：{field.get('kind') or '未知'}"
            if sample:
                detail += "；样例：" + "、".join(sample[:3])
            if values:
                detail += "；可选值：" + "、".join(values[:12])
            lines.append(f"- {name}：{detail}")
        lines.append("")

    target = _table_path(file_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = sanitize.mask_text("\n".join(lines).strip() + "\n")
    with _LOCK:
        target.write_text(text, encoding="utf-8")
    return _relative(target)


def forget_table_upload(file_name: str) -> None:
    """删除原上传表格时，同步移除其自动生成的知识库摘要。"""
    with _LOCK:
        try:
            _table_path(file_name).unlink(missing_ok=True)
        except OSError:
            pass


def remember_qa(question: str, answer: str, thread_id: str = "") -> str | None:
    """追加一条已完成的问答，供后续相似问题检索参考。"""
    question = sanitize.mask_text(str(question or "").strip())
    answer = sanitize.mask_text(str(answer or "").strip())
    if not question or not answer:
        return None
    now = datetime.now()
    lines = [
        f"## 问答时间：{now:%Y-%m-%d %H:%M:%S}",
        f"会话：{thread_id or '未标识'}",
        "",
        "### 问题",
        question,
        "",
        "### 回答",
        answer,
        "",
    ]
    text = "\n".join(lines)
    with _LOCK:
        target = _qa_path(now)
        needs_header = not target.exists() or target.stat().st_size == 0
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            if needs_header:
                handle.write("# 自动学习问答记录\n\n")
            handle.write(text)
    return _relative(target)
