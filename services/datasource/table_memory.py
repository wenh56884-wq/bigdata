"""表格的自动记忆与学习（services/table_memory.py）。

存两类东西，都是**自动**发生的，不需要人工维护：

① **数据卡片**（上传即生成）
   每个文件解析后把「有哪些列、每列是什么类型、取值有哪些、示例值」记下来。
   下次模型写 Python / SQL 前，先看到这张卡片，就不用靠猜列名去试错。

② **问答经验**（每次成功查询后沉淀）
   把「用户问了什么 → 当时用哪张表 → 那段代码是什么」记下来。
   下次问到相似问题时，先把上次成功的写法递给模型——**少走一遍弯路**，
   这也是需求里说的「自动添加记忆和学习」。

存储用单文件 JSON（data/table_memory.json）：
规模小（几百条卡片与经验）、无需额外服务、人可以直接打开看/改。
带 RLock 保证多线程读写安全；写入是「读-改-写全量落盘」，失败不影响主流程。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    from services.ops import sanitize
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.ops import sanitize

_LOCK = threading.RLock()
MAX_EXPERIENCES = 300          # 问答经验上限（超出丢最旧的）
MAX_RECALL = 3                 # 一次最多回想起几条经验
MAX_CARD_CHARS = 1200          # 单张卡片进提示词时的字符上限（防止一堆大表撑爆上下文）


def _path() -> Path:
    configured = (os.getenv("TABLE_MEMORY_PATH") or "").strip()
    base = Path(configured) if configured else \
        Path(__file__).resolve().parents[2] / "data" / "table_memory.json"
    base.parent.mkdir(parents=True, exist_ok=True)
    return base


def _load() -> dict:
    path = _path()
    if not path.exists():
        return {"tables": {}, "experiences": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"tables": {}, "experiences": []}
        data.setdefault("tables", {})
        data.setdefault("experiences", [])
        return data
    except Exception:
        return {"tables": {}, "experiences": []}


def _save(data: dict) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _tokens(text: str) -> set[str]:
    """中文按字、英文数字按词（去掉语气词，减少噪声）。"""
    stop = set("的了吗呢啊呀哦吧和与及是在有这那个我你它把被对于为以")
    words: set[str] = set()
    for piece in re.sub(r"[^\w\u4e00-\u9fff]", " ", str(text or "").lower()).split():
        if re.search(r"[\u4e00-\u9fff]", piece):
            words.update(c for c in piece if c not in stop)
        elif len(piece) > 1:
            words.add(piece)
    return words


# --------------------------------------------------------------------------- #
# ① 数据卡片
# --------------------------------------------------------------------------- #
def remember_table(file_name: str, cards: list[dict]) -> None:
    """记下（或更新）某个文件的数据卡片；同名文件覆盖旧卡片。"""
    with _LOCK:
        data = _load()
        data["tables"][file_name] = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cards": cards,
        }
        _save(data)


def forget_table(file_name: str) -> None:
    with _LOCK:
        data = _load()
        data["tables"].pop(file_name, None)
        data["experiences"] = [e for e in data["experiences"]
                               if e.get("file") != file_name]
        _save(data)


def _mask_values(column_name: str, values: list) -> list:
    """按**列名**脱敏示例值。

    为什么不直接用 mask_text：那是文本正则，认不出「张三」这种没有称谓跟着的裸人名
    （能认「患者张三」）。而数据卡片里的示例值恰恰就是一个个裸值，
    所以必须走「列名判定」这条路（列名叫 姓名/手机号 的那几列才遮）。
    """
    if not values:
        return []
    try:
        _cols, rows, _hits = sanitize.mask_rows(
            [str(column_name)], [[value] for value in values])
        return [row[0] for row in rows]
    except Exception:
        return [str(v) for v in values]


def cards_text(limit_chars: int = MAX_CARD_CHARS) -> str:
    """把所有数据卡片拼成一段给模型看的文字（超过上限就截断）。

    注意：卡片里可能带示例值（人名、电话等），统一过一遍脱敏再输出。
    """
    with _LOCK:
        data = _load()
    if not data["tables"]:
        return ""
    chunks: list[str] = []
    total = 0
    for file_name, entry in data["tables"].items():
        for card in (entry.get("cards") or []):
            lines = [f"文件 {file_name} · 表 {card.get('source_id', '')}"
                     f"（{card.get('n_rows', 0)} 行 × {card.get('n_cols', 0)} 列）："]
            for field in (card.get("columns") or []):
                extra = ""
                if field.get("values"):
                    shown = _mask_values(field["name"], list(field["values"])[:12])
                    extra = f"，取值：{'、'.join(str(v) for v in shown)}"
                sample = ""
                if field.get("sample"):
                    shown = _mask_values(field["name"], list(field["sample"])[:2])
                    sample = f"，例：{'、'.join(str(v) for v in shown)}"
                lines.append(f"  - {field['name']}（{field.get('kind', '')}{sample}{extra}）")
            text = sanitize.mask_text("\n".join(lines))
            chunks.append(text)
            total += len(text)
            if total >= limit_chars:
                break
        if total >= limit_chars:
            break
    return "\n".join(chunks)


# --------------------------------------------------------------------------- #
# ② 问答经验：问什么 → 用什么表 → 怎么写
# --------------------------------------------------------------------------- #
def remember_query(question: str, code: str, table: str = "", file_name: str = "",
                   ok: bool = True, answer: str = "", kind: str = "code") -> None:
    """沉淀一次查询经验（只记成功的，失败的记下来只会误导下一次）。

    kind：code=Python/pandas 写法，sql=SQL 查询；answer 可把最终回答要点一并记下，
    后续 recall_text 会连同答案一起回给模型，便于直接复用。
    """
    if not ok or not (question and code):
        return
    answer = sanitize.mask_text(str(answer or "").strip())[:500]
    with _LOCK:
        data = _load()
        item = {
            "question": str(question)[:200],
            "code": str(code)[:1200],
            "table": str(table or ""),
            "file": str(file_name or ""),
            "kind": str(kind or "code"),
            "answer": answer,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "hits": 1,
        }
        for old in data["experiences"]:
            # 同样的问题 + 同样的代码 → 只累加命中次数，不重复占位置
            if old.get("question") == item["question"] and old.get("code") == item["code"]:
                old["hits"] = int(old.get("hits", 1)) + 1
                old["at"] = item["at"]
                if item["answer"] and not old.get("answer"):
                    old["answer"] = item["answer"]
                old["kind"] = item["kind"] or old.get("kind", "code")
                _save(data)
                return
        data["experiences"].append(item)
        data["experiences"] = data["experiences"][-MAX_EXPERIENCES:]
        _save(data)


def recall(question: str, limit: int = MAX_RECALL) -> list[dict]:
    """按问题相似度回想起用过的写法（词面重叠打分，命中次数做加权）。"""
    keys = _tokens(question)
    if not keys:
        return []
    with _LOCK:
        experiences = list(_load()["experiences"])
    scored = []
    for item in experiences:
        overlap = len(keys & _tokens(item.get("question", "")))
        if not overlap:
            continue
        score = overlap / max(1, len(keys)) + 0.05 * int(item.get("hits", 1))
        scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _score, item in scored[:limit]]


def recall_text(question: str, limit: int = MAX_RECALL) -> str:
    """经验 → 提示词片段（供 find_table / 查询工具带在返回里，模型照着改即可）。"""
    items = recall(question, limit)
    if not items:
        return ""
    lines = ["【记忆：以前这样查过】"]
    for item in items:
        head = f"- 类似问题「{item['question']}」"
        if item.get("table"):
            head += f" 用表 {item['table']}"
        head += f"（用过 {item.get('hits', 1)} 次）"
        lines.append(head)
        label = "SQL" if item.get("kind") == "sql" else "Python"
        lines.append(f"  当时{label}：" + " ".join(str(item["code"]).split())[:300])
        if item.get("answer"):
            lines.append("  当时答案要点：" + " ".join(str(item["answer"]).split())[:220])
    return "\n".join(lines)


def summary() -> dict:
    with _LOCK:
        data = _load()
    return {
        "path": str(_path()),
        "tables": len(data["tables"]),
        "experiences": sum(int(e.get("hits", 1)) for e in data["experiences"]),
        "unique_questions": len(data["experiences"]),
    }


def clear() -> None:
    with _LOCK:
        _save({"tables": {}, "experiences": []})


def _selftest() -> int:
    import tempfile

    ok = ng = 0

    def check(name, got, want):
        nonlocal ok, ng
        if got == want:
            ok += 1
            print(f"  [OK] {name}")
        else:
            ng += 1
            print(f"  [NG] {name}  期望={want!r} 实际={got!r}")

    with tempfile.TemporaryDirectory() as raw:
        os.environ["TABLE_MEMORY_PATH"] = str(Path(raw) / "mem.json")
        try:
            cards = [{"source_id": "名单#Sheet1", "n_rows": 3, "n_cols": 2, "columns": [
                {"name": "姓名", "kind": "文本", "sample": ["张三"], "unique": 3},
                {"name": "等级", "kind": "文本", "sample": ["VIP"], "values": ["VIP", "普通"]},
                {"name": "消费", "kind": "数值", "sample": ["100"], "unique": 3},
            ]}]
            remember_table("名单.xlsx", cards)
            check("卡片已写入", summary()["tables"], 1)
            text = cards_text()
            truthy = lambda cond: cond
            check("卡片含列名", "姓名" in text, True)
            check("枚举取值被列出", "VIP" in text and "普通" in text, True)
            # 姓名列示例值应被脱敏（张三 → 张**）
            check("示例值已脱敏", "张三" not in text, True)

            remember_query("按等级统计人数", "df.groupby('等级').size()", table="t_x", file_name="名单.xlsx")
            check("经验已写入", summary()["unique_questions"], 1)
            check("能回想起来", bool(recall("按等级统计人数")), True)
            check("不相关问题不召回", len(recall("今天天气如何")), 0)
            remember_query("按等级统计人数", "df.groupby('等级').size()", table="t_x")
            check("相同经验只累加次数", summary()["unique_questions"], 1)

            forget_table("名单.xlsx")
            check("删文件后卡片清除", summary()["tables"], 0)
            check("相关经验一并清除", summary()["unique_questions"], 0)
        finally:
            os.environ.pop("TABLE_MEMORY_PATH", None)

    print(f"\n自检：{ok} 项通过，{ng} 项失败")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(_selftest())
