"""统一上传目录：管理员上传的表格文件集中放在 data/uploads（services/uploads.py）。

设计要点：
- **一个目录收口**：不管 Excel 还是 CSV，都进 `app/data/uploads/`（可用 UPLOAD_DIR 改），
  不再散落在各处；表格库（services/tables.py）会连同这个目录一起扫描，上传即可查。
- **落盘即解析**：保存成功后立刻 (1) 解析出「数据卡片」写进记忆 (2) 重建表格索引，
  所以管理员传完文件，用户马上就能问，不需要额外的手工步骤。
- **文件安全**：只取文件名（防目录穿越）、去掉 Windows 非法字符但**保留中文**，
  同名自动改名而不是覆盖。

CLI：python services/uploads.py            # 列出目录里的文件
     python services/uploads.py 文件.xlsx   # 试解析并打印数据卡片
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    from services import spreadsheet
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services import spreadsheet

_LOCK = threading.RLock()

DEFAULT_DIRNAME = "uploads"
MAX_MB = float(os.getenv("UPLOAD_MAX_MB", "50"))
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def directory() -> Path:
    """统一目录：默认 app/data/uploads。"""
    configured = (os.getenv("UPLOAD_DIR") or "").strip()
    base = Path(configured) if configured else Path(__file__).resolve().parents[1] / "data" / DEFAULT_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_name(filename: str) -> str:
    """只保留文件名本体，去掉非法字符（中文保留），空名兜底。"""
    name = Path(str(filename or "")).name
    name = _ILLEGAL.sub("_", name).strip(" .")
    return name or "未命名表格"


def _unique_path(target: Path) -> Path:
    """同名不覆盖：a.xlsx → a_1.xlsx → a_2.xlsx。"""
    if not target.exists():
        return target
    stem, suffix, index = target.stem, target.suffix, 1
    while True:
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


# --------------------------------------------------------------------------- #
# 数据卡片：解析一次文件，抽出「列名 / 类型 / 示例值 / 取值分布」
# --------------------------------------------------------------------------- #
def profile_file(path: str | Path, max_rows: int = 5000) -> list[dict]:
    """解析文件 → 每张表一张数据卡片（供记忆与前端展示）。"""
    path = Path(path)
    cards: list[dict] = []
    for source_id, table in spreadsheet.parse_file(path):
        columns = list(table.get("columns") or [])
        rows = list(table.get("rows") or [])[:max_rows]
        numeric = list(table.get("numeric") or [])
        fields = []
        for index, name in enumerate(columns):
            values = [row[index] for row in rows if index < len(row)]
            values = [v for v in values if v not in (None, "")]
            sample = [str(v) for v in values[:3]]
            unique = len({str(v) for v in values})
            kind = "数值" if (index < len(numeric) and numeric[index]) else "文本"
            field = {"name": str(name), "kind": kind, "sample": sample,
                     "unique": unique, "empty": len(rows) - len(values) if rows else 0}
            if kind == "文本" and 0 < unique <= 12:          # 枚举值全列出来，模型才知道有哪些取值
                field["values"] = sorted({str(v) for v in values})
            fields.append(field)
        cards.append({
            "source_id": source_id,
            "sheet": str(source_id).split("#")[-1] if "#" in str(source_id) else "",
            "n_rows": len(list(table.get("rows") or [])),
            "n_cols": len(columns),
            "columns": fields,
            "preview": [[row[i] if i < len(row) else None for i in range(len(columns))]
                        for row in rows[:2]],
        })
    return cards


def _card_brief(card: dict) -> str:
    """数据卡片 → 一段给模型看的文字（列名 + 类型 + 示例 + 枚举取值）。"""
    lines = [f"表 {card['source_id']}：{card['n_rows']} 行 × {card['n_cols']} 列"]
    for field in card["columns"]:
        extra = ""
        if field.get("values"):
            extra = f"，取值：{'、'.join(field['values'][:12])}"
        sample = f"，例：{'、'.join(field['sample'][:2])}" if field.get("sample") else ""
        lines.append(f"  - {field['name']}（{field['kind']}{sample}{extra}）")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 落盘 / 列表 / 删除（上传即解析）
# --------------------------------------------------------------------------- #
def save(upload_name: str, data: bytes) -> dict:
    """保存上传文件，并立刻解析 + 写记忆 + 重建索引。返回条目信息。"""
    with _LOCK:
        base = directory()
        target = _unique_path(base / _safe_name(upload_name))
        size = len(data or b"")
        if size <= 0:
            raise ValueError("文件内容为空")
        if size > MAX_MB * 1024 * 1024:
            raise ValueError(f"文件超过 {MAX_MB:.0f} MB 上限（实际 {size / 1024 / 1024:.1f} MB）")
        target.write_bytes(data)

        entry = {
            "name": target.name,
            "stored_as": target.name,
            "size": size,
            "sha1": _sha1(target),
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "suffix": target.suffix.lower(),
            "tables": 0,
            "rows": 0,
            "status": "已解析",
            "message": "",
        }
        try:
            cards = profile_file(target)
            entry["tables"] = len(cards)
            entry["rows"] = sum(c["n_rows"] for c in cards)
            if not cards:
                entry["status"] = "未识别"
                entry["message"] = "没解析出表格（文件为空或格式不支持）"
            else:
                # ① 写记忆：这个文件的结构从今往后都在「数据卡片」里
                from services import table_memory
                table_memory.remember_table(target.name, cards)
        except Exception as exc:                       # 解析失败也要保留文件，只是标个状态
            entry["status"] = "解析失败"
            entry["message"] = f"{type(exc).__name__}: {exc}"

        # ② 重建表格索引：让 find_table / query_tables 立刻能查到它
        try:
            from services import tables
            tables.build(force=True, quiet=True)
        except Exception as exc:
            entry["message"] = (entry["message"] + f"；索引重建失败：{exc}").strip("；")
        return entry


def list_files() -> list[dict]:
    """列出目录里的文件（含规模与解析状态）。"""
    base = directory()
    items: list[dict] = []
    for path in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.name.startswith(".") or path.name.startswith("~$"):
            continue
        try:
            stat = path.stat()
            items.append({
                "name": path.name,
                "size": stat.st_size,
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "suffix": path.suffix.lower(),
                "supported": spreadsheet.supported(path),
            })
        except OSError:
            continue
    return items


def delete(name: str) -> bool:
    """删除文件（连带重建索引与清记忆）。"""
    with _LOCK:
        target = directory() / _safe_name(name)
        if not target.is_file():
            return False
        target.unlink()
        try:
            from services import table_memory
            table_memory.forget_table(target.name)
        except Exception:
            pass
        try:
            from services import tables
            tables.build(force=True, quiet=True)
        except Exception:
            pass
        return True


def load_dataframe(table_name: str):
    """按表名（或文件名关键字）把表格读成 pandas DataFrame，供沙箱执行。

    先精确匹配表名，再退化为「文件名 / sheet 名模糊匹配」——模型常常只知道文件名。
    """
    import pandas as pd

    from services import tables
    if not tables.DB_PATH.exists():
        raise ValueError("表格索引还没建好（先上传文件或执行一次重建）")
    conn = sqlite3.connect(str(tables.DB_PATH))
    try:
        meta = conn.execute(
            "SELECT table_name, source_id, n_rows FROM _tables").fetchall()
        hit = None
        for name, source_id, _n in meta:
            if name == table_name or source_id == table_name:
                hit = name
                break
        if hit is None:                                # 模糊：文件名或 sheet 名包含即可
            key = str(table_name).lower()
            fuzzy = [n for n, sid, _x in meta
                     if key in n.lower() or key in str(sid).lower()]
            if not fuzzy:
                raise ValueError(f"没有找到表 {table_name}（先用 find_table 召回候选表）")
            hit = fuzzy[0]
        frame = pd.read_sql_query(f'SELECT * FROM "{hit}"', conn)
        return frame, hit
    finally:
        conn.close()


def _main(argv: list[str]) -> int:
    if argv:
        for arg in argv:
            path = Path(arg)
            cards = profile_file(path)
            print(f"\n=== {path.name} ===")
            for card in cards:
                print(_card_brief(card))
        return 0
    items = list_files()
    print(f"统一目录：{directory()}")
    if not items:
        print("（还没有上传任何文件）")
        return 0
    for item in items:
        flag = "可解析" if item["supported"] else "不支持"
        print(f"  {item['name']:<40} {item['size'] / 1024:>9.1f} KB  "
              f"{item['uploaded_at']}  {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
