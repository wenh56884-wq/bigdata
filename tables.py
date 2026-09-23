"""非结构化表格解析与查询：把「非结构化数据/」里的 markdown / HTML 表格变成可 SQL 查询的数据。

一句话链路
----------
    非结构化数据/*-数据.md   ──解析──▶  规范表格（表头 + 行 + 数值清洗）
                            ──入库──▶  data/tables.sqlite3（每张源表一个物理表 + _tables 元数据）
                            ──查询──▶  Agent 四个工具：list_table_sets / find_table / describe_table / query_tables

为什么用 SQLite，而不是「让模型写 pandas 代码」
----------------------------------------------
1. **零新依赖**：sqlite3 是标准库，而 pandas 不在本项目的 requirements.txt 里（之前那版就因为它没装而整条链路跑不起来）；
2. **模型更会写 SQL**：准确率明显高于现场生成 pandas，而且与项目既有的 execute_sql（MySQL 只读查询）
   完全同构，工具使用习惯一致，不用教第二套范式；
3. **答案可复现**：数字都是数据库真算出来的，不是模型看着表格心算出来的。

解析规则（对照真实数据）
------------------------
- 数据文件按 === 表id === 分块，每块一个代码围栏，围栏语言是 markdown（管道表）或 html（<table>）；
- 表头可能带空首列（形如 ||date|OT|），空表头列自动命名为 col1/col2…，重名自动加 _2；
- 数值清洗：货币符号、千分位逗号、百分号、括号负数、(x) 形式的备注都会被归一成真正的数字，
  只对「数值列」（可解析比例 ≥ 80%）生效，其它列原样保留文本；
- 列亲和性：数值列用 NUMERIC，文本列用 TEXT —— 这样 "01234" 不会被吃成 1234。

只读安全
--------
查询走 file:...?mode=ro 只读连接，并且只放行单条 SELECT / WITH 语句，
ATTACH / PRAGMA / INSERT / DROP 等一律拒绝（连数据库文件都打不开写权限）。

命令行
------
    python tables.py --build              # 重建索引（首次查询也会自动建）
    python tables.py --sets               # 三个数据集概况
    python tables.py --stats              # 规模统计
    python tables.py --find "问题原文"     # 关键词召回候选表
    python tables.py --info t_xxx         # 看某张表的列与预览
    python tables.py --sql "SELECT ..."   # 直接查（只读）
    python tables.py --questions table_query --limit 5   # 看评测题样例
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

from rag import tokenize  # 复用中文友好的分词（关键词召回用），避免再写一套

PROJECT_ROOT = Path(__file__).resolve().parent
TABLE_DATA_DIR = Path(os.getenv("TABLE_DATA_DIR") or (PROJECT_ROOT / "非结构化数据"))
DB_PATH = PROJECT_ROOT / "data" / "tables.sqlite3"

# 三份评测集：数据文件 / 题目文件 / 中文名
DATASETS: dict[str, dict] = {
    "table_query": {
        "file": "Table_Query-数据.md",
        "task": "Table_Query_task.json",
        "title": "表格查询（Table_Query）",
        "desc": "单表事实型问答：某列叫什么、第一行第一格是什么、某年某指标的值等",
    },
    "domain_ops": {
        "file": "Table_Domain-specific_Operations-数据.md",
        "task": "Table_Domain-specific_Operations_task.json",
        "title": "领域运算（Domain-specific Operations）",
        "desc": "金融/能源等专业表上的加减乘除、环比、占比、区间统计等运算型问答",
    },
    "multi_step": {
        "file": "Multi-step_Retrieval-数据.md",
        "task": "Multi-step_Retrieval_task.json",
        "title": "多步检索（Multi-step Retrieval）",
        "desc": "大表（上万行）上的多步筛选/聚合，如反事实假设、按条件回溯明细",
    },
}

_META_TABLE = "_tables"
_BUILD_INFO = "_build_info"

# 提问里的功能词：本身没有检索价值，但在这份语料里很稀有（IDF 高），
# 不滤掉的话「第一 / 年的 / 哪个」这类词会把真正的业务词挤下去。
_QUESTION_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "及", "或", "把", "被", "对", "从", "到", "为", "有",
    "中", "里", "上", "下", "多少", "哪个", "哪些", "什么", "怎么", "如何", "是否", "请问",
    "帮我", "请", "看下", "一下", "这个", "那个", "这些", "那些", "表格", "数据", "值", "行",
    "列", "第一", "第二", "第三", "年的", "年的", "吗", "呢", "以及", "并且", "然后", "等于",
    "分别", "一共", "总共", "如果", "假设", "并未", "发生", "以下", "上面", "下面",
}
_MEM_LOCK = threading.RLock()
_INDEX_CACHE: dict = {"mtime": None, "items": None, "df": None}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 一、解析：=== 块 → 表格
# --------------------------------------------------------------------------- #
def split_blocks(text: str) -> list[tuple[str, str]]:
    """把数据文件按 === 表id === 切成 (id, 正文) 列表。"""
    parts = re.split(r"^===\s*(.+?)\s*===$", text or "", flags=re.M)
    return [
        (parts[i].strip(), parts[i + 1])
        for i in range(1, len(parts) - 1, 2)
        if parts[i].strip()
    ]


def extract_fence(body: str) -> tuple[str, str]:
    """取出块里的代码围栏内容，返回 (语言, 内容)；没有围栏就把整块当内容。"""
    match = re.search(r"[\x60]{3}([a-zA-Z]*)\s*\n(.*?)[\x60]{3}", body or "", flags=re.S)
    if match:
        return (match.group(1) or "").strip().lower(), match.group(2)
    return "", (body or "").strip()


def _split_md_row(line: str) -> list[str]:
    """拆一行管道表：去掉首尾竖线后按竖线切分。"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def parse_markdown_table(content: str) -> tuple[list[str], list[list[str]]] | tuple[None, None]:
    """解析管道表（|a|b| / |---|:--:| / |1|2|）。"""
    rows = [_split_md_row(line) for line in (content or "").splitlines() if line.strip().startswith("|")]
    rows = [row for row in rows if row and not _is_separator_row(row)]
    if len(rows) < 2:
        return None, None
    return rows[0], rows[1:]


class _HtmlTableParser(HTMLParser):
    """只取第一个 <table>：把 tr 收集成行，td/th 收集成单元格。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.header_rows = 0
        self._table_depth = 0
        self._done = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_head = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "table":
            self._table_depth += 1
        elif tag == "thead":
            self._in_head = True
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if self._done:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
                if self._in_head and len(self.rows) == 1:
                    self.header_rows = 1
            self._row = None
        elif tag == "thead":
            self._in_head = False
            if self.rows:
                self.header_rows = 1
        elif tag == "table":
            self._table_depth -= 1
            self._done = True          # 只要第一张表


def parse_html_table(content: str) -> tuple[list[str], list[list[str]]] | tuple[None, None]:
    """解析 HTML 表格；无 thead 时把首行当表头。"""
    parser = _HtmlTableParser()
    try:
        parser.feed(content or "")
        parser.close()
    except Exception:
        return None, None
    rows = parser.rows
    if len(rows) < 1:
        return None, None
    header_idx = 0 if parser.header_rows else 0
    headers = rows[header_idx]
    body = rows[header_idx + 1:] if len(rows) > 1 else []
    if not body:                      # 只有一行：当成「表头 + 无数据」
        return headers, []
    return headers, body


_CURRENCY = "$€£¥₩₹"
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def to_number(value: str) -> float | int | None:
    """把脏单元格归一成数字；不是数字返回 None。

    处理的样式（都来自真实数据）：$ 100.00 / 1,234.5 / 23% / (6.5) 表示 -6.5 /
    -6.5 ( 6.5 ) 取前面的 -6.5 / 1 234.5（空格千分位）。
    """
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", " ").replace("\u200b", "")
    if not text or len(text) > 40:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    if "(" in text:                       # 去掉括号里的备注，如 "-6.5 ( 6.5 )" → "-6.5"
        text = text.split("(", 1)[0].strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    for symbol in _CURRENCY:
        text = text.replace(symbol, "")
    text = text.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", text):
        text = text.replace(",", "")
    if not _NUM_RE.match(text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if negative:
        number = -number
    return int(number) if number.is_integer() and abs(number) < 1e15 else number


def normalize_columns(headers: list[str], width: int) -> list[str]:
    """表头归一：空→colN、去重、限长（重名加 _2）。"""
    names: list[str] = []
    seen: set[str] = set()
    for index in range(width):
        raw = (headers[index] if index < len(headers) else "") or ""
        name = re.sub(r"\s+", " ", str(raw).replace("\ufeff", "")).strip()
        if not name:
            name = f"col{index + 1}"
        # 截断后再去一次首尾空格，避免列名以空格结尾（难看，也容易在拼 SQL 时踩坑）
        name = name[:80].strip() or f"col{index + 1}"
        base, suffix = name, 2
        while name.lower() in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        seen.add(name.lower())
        names.append(name)
    return names


def normalize_rows(rows: list[list[str]], width: int) -> list[list[str]]:
    """把每行补齐/截断到表头宽度，并按需补空单元格。"""
    out = []
    for row in rows:
        if len(row) < width:
            row = list(row) + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        out.append([("" if cell is None else str(cell).strip()) for cell in row])
    return out


def detect_numeric_columns(rows: list[list[str]], width: int) -> list[bool]:
    """判断哪些列是数值列：非空单元格里能解析成数字的比例 ≥ 80%，且至少 2 个。

    阈值取 2 而不是 3：这份评测集里大量小表只有 2~3 行（例如「某指标 2011/2012 两年数值」），
    卡在 3 会让 「$ 34」「35」 这类真正的数值退化成文本，后面的百分比变化就算不出来。
    """
    flags = []
    for col in range(width):
        values = [row[col] for row in rows if row[col] != ""]
        if not values:
            flags.append(False)
            continue
        numeric = sum(1 for value in values if to_number(value) is not None)
        flags.append(numeric >= 2 and numeric / len(values) >= 0.8)
    return flags


def coerce_rows(rows: list[list[str]], numeric: list[bool]) -> list[list]:
    """数值列把单元格换成真正的数字（该列里非数值的单元格保持文本）。"""
    if not any(numeric):
        return rows
    out = []
    for row in rows:
        new_row = []
        for index, cell in enumerate(row):
            if numeric[index] and cell != "":
                number = to_number(cell)
                new_row.append(number if number is not None else cell)
            else:
                new_row.append(cell)
        out.append(new_row)
    return out


def parse_table_block(body: str) -> dict | None:
    """把一个 === 块解析成 {columns, rows, numeric, is_html}；不是表格返回 None。"""
    lang, content = extract_fence(body)
    headers, rows = (None, None)
    is_html = False
    if lang.startswith("html") or "<table" in content[:2000].lower():
        headers, rows = parse_html_table(content)
        is_html = headers is not None
    if headers is None:
        headers, rows = parse_markdown_table(content)
    if not headers:
        return None
    width = max([len(headers)] + [len(row) for row in rows[:50]] or [0])
    if width <= 0:
        return None
    columns = normalize_columns(headers, width)
    rows = normalize_rows(rows, width)
    numeric = detect_numeric_columns(rows, width)
    return {
        "columns": columns,
        "rows": coerce_rows(rows, numeric),
        "numeric": numeric,
        "is_html": is_html,
    }


# --------------------------------------------------------------------------- #
# 二、入库：SQLite
# --------------------------------------------------------------------------- #
def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_name(source_id: str) -> str:
    return "t_" + re.sub(r"[^0-9a-zA-Z_]", "_", source_id)[:60]


def _search_blob(columns: list[str], rows: list[list], limit_values: int = 20) -> str:
    """给召回用的检索文本：表头 + 前几行 + 各列的去重短值。"""
    parts = list(columns)
    for row in rows[:3]:
        parts.append(" ".join(str(cell) for cell in row if cell != ""))
    for index, name in enumerate(columns):
        seen = 0
        for row in rows:
            value = str(row[index]) if index < len(row) else ""
            if not value or len(value) > 30:
                continue
            parts.append(value)
            seen += 1
            if seen >= limit_values:
                break
    blob = " | ".join(parts)[:2000]
    # 再补一份「分隔符归一」的副本：列名常写成 cash_type / net-income / a.b，
    # 用户提问说的是 cash / coffee，直接切词对不上，补一份把 _ . - / 换成空格的文本供召回。
    normalized = re.sub(r"[_./\-]+", " ", blob)
    return (blob + " | " + normalized)[:4000]


def _db_connect(readonly: bool = False) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _source_signature() -> dict:
    """源数据文件的规模签名（用于判断要不要重建索引）。"""
    signature = {}
    for key, meta in DATASETS.items():
        path = TABLE_DATA_DIR / meta["file"]
        try:
            stat = path.stat()
            signature[key] = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
        except OSError:
            signature[key] = None
    return signature


def _read_build_info() -> dict:
    try:
        with _db_connect(readonly=True) as conn:
            rows = conn.execute(f"SELECT key, value FROM {_BUILD_INFO}").fetchall()
        return {row["key"]: row["value"] for row in rows}
    except sqlite3.Error:
        return {}


def iter_parsed_tables() -> Iterator[tuple[str, str, dict]]:
    """逐张产出 (dataset_key, source_id, 解析结果)。

    解析结果统一从这里取数，索引构建与命令行查询共用同一份逻辑。
    """
    for key, meta in DATASETS.items():
        path = TABLE_DATA_DIR / meta["file"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for source_id, body in split_blocks(text):
            table = parse_table_block(body)
            if table and table["columns"]:
                yield key, source_id, table


def build(force: bool = False, quiet: bool = False) -> dict:
    """解析全部数据文件并重建 SQLite 索引；返回统计信息。"""
    started = time.time()
    if DB_PATH.exists() and not force:
        info = _read_build_info()
        if info.get("signature") == json.dumps(_source_signature(), ensure_ascii=False):
            return {**json.loads(info.get("stats") or "{}"), "rebuilt": False}

    stats = {"datasets": {}, "tables": 0, "rows": 0, "html_tables": 0, "empty_tables": 0}
    tmp_path = DB_PATH.with_suffix(".building")
    if tmp_path.exists():
        tmp_path.unlink()
    conn = sqlite3.connect(str(tmp_path))
    try:
        conn.execute(
            f"CREATE TABLE {_META_TABLE} ("
            "table_name TEXT PRIMARY KEY, source_id TEXT, dataset TEXT, dataset_title TEXT,"
            "n_rows INTEGER, n_cols INTEGER, columns TEXT, numeric_columns TEXT,"
            "is_html INTEGER, source_file TEXT, search_blob TEXT, sample TEXT)"
        )
        conn.execute(f"CREATE TABLE {_BUILD_INFO} (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE INDEX idx_tables_dataset ON _tables(dataset)")
        per_dataset: dict[str, dict] = {
            key: {"tables": 0, "rows": 0, "html_tables": 0} for key in DATASETS
        }
        for key, source_id, table in iter_parsed_tables():
            meta = DATASETS[key]
            table_name = _table_name(source_id)
            columns = table["columns"]
            numeric = table["numeric"]
            ddl_cols = ", ".join(
                f"{_quote(name)} {'NUMERIC' if numeric[i] else 'TEXT'}"
                for i, name in enumerate(columns)
            )
            conn.execute(f"CREATE TABLE {_quote(table_name)} ({ddl_cols})")
            placeholders = ", ".join("?" for _ in columns)
            if table["rows"]:
                conn.executemany(
                    f"INSERT INTO {_quote(table_name)} VALUES ({placeholders})",
                    table["rows"],
                )
            conn.execute(
                f"INSERT INTO {_META_TABLE} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    table_name,
                    source_id,
                    key,
                    meta["title"],
                    len(table["rows"]),
                    len(columns),
                    json.dumps(columns, ensure_ascii=False),
                    json.dumps([c for c, flag in zip(columns, numeric) if flag], ensure_ascii=False),
                    1 if table["is_html"] else 0,
                    meta["file"],
                    _search_blob(columns, table["rows"]),
                    json.dumps(
                        [[("" if cell is None else cell) for cell in row] for row in table["rows"][:3]],
                        ensure_ascii=False,
                    )[:4000],
                ),
            )
            row = per_dataset[key]
            row["tables"] += 1
            row["rows"] += len(table["rows"])
            row["html_tables"] += 1 if table["is_html"] else 0
        for key, meta in DATASETS.items():
            path = TABLE_DATA_DIR / meta["file"]
            row = per_dataset[key]
            stats["datasets"][key] = {
                "title": meta["title"], "tables": row["tables"], "rows": row["rows"],
                "html_tables": row["html_tables"], "skipped_blocks": 0,
                "file": meta["file"], "bytes": path.stat().st_size if path.exists() else 0,
            }
            stats["tables"] += row["tables"]
            stats["rows"] += row["rows"]
            stats["html_tables"] += row["html_tables"]
            if not quiet:
                print(f"[tables] {meta['title']}：{row['tables']} 张表 / {row['rows']} 行"
                      f"（HTML 表 {row['html_tables']}）", flush=True)
        conn.execute("CREATE INDEX idx_tables_name ON _tables(table_name)")
        conn.execute(
            f"INSERT INTO {_BUILD_INFO} VALUES ('built_at', ?)", (_now(),))
        conn.execute(
            f"INSERT INTO {_BUILD_INFO} VALUES ('signature', ?)",
            (json.dumps(_source_signature(), ensure_ascii=False),))
        stats["built_at"] = _now()
        stats["seconds"] = round(time.time() - started, 1)
        conn.execute(f"INSERT INTO {_BUILD_INFO} VALUES ('stats', ?)",
                     (json.dumps(stats, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp_path, DB_PATH)
    with _MEM_LOCK:
        _INDEX_CACHE.update({"mtime": None, "items": None, "df": None})
    stats["rebuilt"] = True
    return stats


def ensure(force: bool = False) -> dict:
    """确保索引可用（不存在或源文件变了就重建），返回统计。"""
    try:
        if DB_PATH.exists() and not force:
            info = _read_build_info()
            if info.get("signature") == json.dumps(_source_signature(), ensure_ascii=False):
                return {**json.loads(info.get("stats") or "{}"), "rebuilt": False}
    except Exception:
        pass
    return build(force=force)


def available() -> bool:
    """数据目录与至少一份数据文件是否存在（决定要不要给 Agent 挂这些工具）。"""
    if not TABLE_DATA_DIR.exists():
        return False
    return any((TABLE_DATA_DIR / meta["file"]).exists() for meta in DATASETS.values())


# --------------------------------------------------------------------------- #
# 三、召回与查询
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 中文术语 → 英文检索词对照表（人工整理，本地规则、不耗模型）
# --------------------------------------------------------------------------- #
# 为什么要它：表内容是英文，而用户用中文提问（「现金支付里卖得最多的咖啡品类」），
# 纯关键词召回天然对不上。这份对照表把中文业务词翻成表里真实会出现的英文词，
# 直接补进检索词里 —— 效果等价于「先让模型翻译一遍」，但不花钱、且结果稳定。
#
# 词条覆盖三份评测集的主题（实测统计过题目与表内容）：
#   咖啡消费流水 / 气象 / 新能源与汽车 / 企业财报与金融 / 保险 / 地区经济 / 体育与餐饮。
# 用法：find_tables() 会自动扩展；也可以看 analyze_table_query 的返回值。
_CN_EN_TERMS: dict[str, tuple[str, ...]] = {
    # —— 咖啡消费（multi_step）——
    "咖啡": ("coffee", "coffee_name"), "拿铁": ("latte",), "卡布奇诺": ("cappuccino",),
    "美式": ("americano",), "浓缩": ("espresso",), "摩卡": ("mocha",),
    "品类": ("category", "name"), "现金": ("cash", "cash_type"), "刷卡": ("card",),
    "信用卡": ("card",), "支付": ("cash", "card", "payment"), "消费": ("money", "amount"),
    "花费": ("money", "amount"), "单价": ("money", "price"), "杯": ("count",),
    # —— 气象（multi_step）——
    "气象": ("weather",), "天气": ("weather",), "温度": ("temperature",),
    "湿度": ("humidity",), "风速": ("wind",), "降水": ("precipitation",),
    "降雨": ("precipitation",), "云量": ("cloud",), "气压": ("pressure",),
    "紫外线": ("uv",), "能见度": ("visibility",), "季节": ("season",),
    # —— 新能源 / 汽车（multi_step）——
    "新能源": ("powertrain", "ev"), "电动": ("powertrain", "ev"), "车型": ("mode", "category"),
    "动力": ("powertrain",), "续航": ("range",), "里程": ("range", "mileage"),
    "销量": ("sales", "value"), "排放": ("emission",), "油耗": ("consumption",),
    # —— 企业财报 / 金融（domain_ops）——
    "收入": ("revenue", "income", "sales"), "营收": ("revenue",), "净收入": ("net income", "income"),
    "净利润": ("net income", "profit"), "毛利": ("gross margin", "gross profit"),
    "利差": ("credit spread", "spread"), "信用利差": ("credit spread",),
    "基点": ("basis point",), "利率": ("interest rate",), "汇率": ("exchange rate",),
    "资产": ("asset",), "负债": ("liabilit",), "权益": ("equity",), "现金流": ("cash flow",),
    "每股": ("per share", "earnings"), "股息": ("dividend",), "市值": ("market cap",),
    "成本": ("cost",), "费用": ("expense", "cost"), "利润": ("profit", "income"),
    "电价": ("electricity", "power price"), "零售电价": ("retail electricity", "electricity"),
    "煤": ("coal",), "天然气": ("natural gas", "gas"), "石油": ("oil", "petroleum"),
    "发电": ("generation", "power"), "装机": ("capacity",),
    # —— 保险 / 地区经济（multi_step）——
    "保险": ("insurance",), "保费": ("premium",), "理赔": ("claim",), "索赔": ("claim",),
    "扣除额": ("deductible",), "保单": ("policy",), "客户": ("customer", "client"),
    "年龄": ("age",), "地区生产总值": ("gdp", "gross domestic product"),
    "生产总值": ("gdp",), "第一产业": ("primary industry",), "第二产业": ("secondary industry",),
    "第三产业": ("tertiary industry",), "地区": ("region", "area", "country"),
    # —— 体育 / 餐饮 / 通用（table_query）——
    "球员": ("player",), "球队": ("team", "club"), "俱乐部": ("club",),
    "比赛": ("match", "game", "championship"), "赛事": ("championship",),
    "冠军": ("champion", "winner"), "身高": ("height",), "体重": ("weight",),
    "谓词": ("predicate",), "主语": ("subject",), "宾语": ("object",),
    "餐厅": ("restaurant", "eattype"), "菜品": ("food", "menu"),
    # —— 时间 / 统计口径（通用）——
    "年份": ("year",), "年度": ("year", "annual"), "季度": ("quarter",),
    "月份": ("month",), "日期": ("date",), "时间": ("date", "datetime", "time"),
    "同比": ("year over year", "yoy"), "环比": ("month over month", "mom"),
    "增长": ("growth", "increase"), "下降": ("decrease", "decline"),
    "占比": ("share", "percentage", "percent"), "比重": ("share", "percent"),
    "百分比": ("percent", "percentage"), "比率": ("ratio", "rate"),
    "平均": ("average", "mean", "avg"), "合计": ("total", "sum"),
    "总数": ("total", "count"), "数量": ("count", "number", "quantity"),
    "排名": ("rank", "ranking"), "最高": ("highest", "max", "top"), "最低": ("lowest", "min"),
    "最多": ("most", "top"), "最少": ("least", "bottom"), "总额": ("total", "amount"),
    "金额": ("amount", "money", "value"), "价值": ("value",), "单位": ("unit",),
    "状态": ("status", "type"), "类别": ("category", "type"), "编号": ("id", "number"),
    "名称": ("name",), "地点": ("location", "place", "area"), "国家": ("country",),
    "城市": ("city",), "地址": ("address",),
}

# 提问元语言：题目在描述「表格本身」（第几列 / 单元格 / 列名），不含业务信息，
# 参与检索只会把噪声顶上来（实测：它们能占题目词的一半以上）。统计自 787 道题。
_QUESTION_STOPWORDS |= {
    "单元", "元格", "单元格", "内容", "列名", "行名", "表头", "字段", "编码", "第几", "几列", "几行",
    "左边", "右边", "左列", "右列", "左边单", "右边单", "具体", "除去", "包含", "称为", "默认",
    "完整", "表格", "标注", "标记", "起点", "起始", "起始点", "第一", "第二", "第三", "中第", "从第",
    "给定", "下列", "以下", "上述", "标识", "说明", "描述", "对应", "数据", "行号", "排序", "位于",
    "格里", "格内", "格里写", "怎么", "怎样", "多少", "哪个", "哪些", "什么", "请问", "以及", "并且",
    "然后", "如果", "假设", "并未", "发生", "一个", "可以", "需要", "进行", "之间", "之后", "之前",
}


def expand_terms(text: str) -> list[str]:
    """把中文问题里的术语扩展成英文检索词（本地规则，最长匹配优先，去重保序）。"""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    # 先长后短，避免「信用利差」被拆成「利差」+ 噪声
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        size = len(seg)
        used = [False] * size
        for width in (4, 3, 2):
            for start in range(0, size - width + 1):
                if any(used[start:start + width]):
                    continue
                word = seg[start:start + width]
                terms = _CN_EN_TERMS.get(word)
                if not terms:
                    continue
                for term in terms:
                    if term not in seen:
                        seen.add(term)
                        found.append(term)
                for index in range(start, start + width):
                    used[index] = True
    return found


def _document_frequency(items: list[dict]) -> dict[str, int]:
    """统计每个 token 出现在多少张表里（IDF 用）。

    没有这一步的话，「2019 / 2011」这种到处都有的年份会把分数顶满，
    真正有区分度的词（jpmorgan、Latte、ANON-0000-0000-0001）反而被淹没。
    """
    df: dict[str, int] = {}
    for item in items:
        for token in item["tokens"]:
            df[token] = df.get(token, 0) + 1
    return df


_META_KEYS = ("table_name", "source_id", "dataset", "dataset_title", "n_rows", "n_cols",
              "columns", "numeric_columns", "is_html", "source_file", "search_blob", "sample")


def _meta_rows() -> list[dict]:
    """读取全部表元数据（本地 SQLite 索引）。"""
    try:
        with _db_connect(readonly=True) as conn:
            rows = conn.execute(
                "SELECT " + ", ".join(_META_KEYS) + " FROM " + _META_TABLE
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def _meta_row(table_name: str) -> dict | None:
    """读单张表的元数据。"""
    try:
        with _db_connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT " + ", ".join(_META_KEYS) + " FROM " + _META_TABLE
                + " WHERE table_name = ?", (table_name,)
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None


def _load_index() -> list[dict]:
    """把 _tables 元数据加载进内存做召回（带缓存）。"""
    with _MEM_LOCK:
        try:
            stamp = DB_PATH.stat().st_mtime
        except OSError:
            return []
        if _INDEX_CACHE["mtime"] == stamp and _INDEX_CACHE["items"] is not None:
            return _INDEX_CACHE["items"]
        items = []
        for row in _meta_rows():
            blob = (row.get("search_blob") or "").lower()
            items.append({
                "table": row["table_name"],
                "source_id": row["source_id"],
                "dataset": row["dataset"],
                "dataset_title": row["dataset_title"],
                "n_rows": row["n_rows"],
                "n_cols": row["n_cols"],
                "columns": json.loads(row["columns"] or "[]"),
                "tokens": set(tokenize(blob)),
                "blob": blob,
            })
        _INDEX_CACHE.update({"mtime": stamp, "items": items, "df": _document_frequency(items)})
        return items


def _idf(df: dict, total: int, token: str) -> float:
    """IDF：越稀有的词权重越高（出现 1 次的词 ≈ 6.3，出现 400 次的词 ≈ 0.67）。"""
    import math

    return math.log((total + 1) / (df.get(token, 0) + 0.5))


def find_tables(question: str, dataset: str = "", limit: int = 5,
                extra_keywords: str = "") -> list[dict]:
    """按关键词召回候选表（IDF 加权）。

    三种入口都能用：
    - 问题里直接带表 id（15 位十六进制，如 b40962fe65f24d9）→ 直接返回那张表；
    - 问题里带了表里的具体取值（Latte / ANON-0000-0000-0001 / chunichi dragons）→ 稀有词权重高，命中准；
    - 纯中文问题（表内容是英文时）→ 由调用方先翻译成英文关键词，从 extra_keywords 传进来再召回。
    """
    items = _load_index()
    if not items:
        return []
    text = f"{question or ''} {extra_keywords or ''}".strip()
    # 中文术语 → 英文检索词（本地对照表，不花模型钱）：中文提问 / 英文表格对不上时靠它
    expanded = expand_terms(text)
    if expanded:
        text = text + " " + " ".join(expanded)
    id_match = re.search(r"\b([0-9a-f]{12,20})\b", text.lower())
    if id_match:
        name = _table_name(id_match.group(1))
        direct = [item for item in items if item["table"] == name]
        if direct:
            return [_hit_payload(direct[0], [id_match.group(1)], 999.0)]
    if dataset:
        wanted = _match_dataset(dataset)
        if wanted:
            items = [item for item in items if item["dataset"] == wanted]
    query_tokens = {
        token for token in tokenize(text.lower())
        if len(token) > 1 and token not in _QUESTION_STOPWORDS
    }
    if not query_tokens:
        return []
    with _MEM_LOCK:
        df = _INDEX_CACHE.get("df") or _document_frequency(items)
    total = max(len(items), 1)
    scored = []
    for item in items:
        hits = query_tokens & item["tokens"]
        if not hits:
            continue
        score = sum(_idf(df, total, token) for token in hits)
        # 单个偶合词（哪怕很长）不足以入选，除非它足够稀有
        if score < 1.5:
            continue
        scored.append((score, len(hits), item, sorted(hits, key=lambda t: -_idf(df, total, t))[:6]))
    scored.sort(key=lambda pair: (-pair[0], -pair[1], pair[2]["table"]))
    results = []
    for score, hit_count, item, hits in scored[:limit]:
        results.append(_hit_payload(item, hits, score))
    return results


def _hit_payload(item: dict, hits: list[str], score: float) -> dict:
    """召回的返回结构（工具层直接转成给模型看的文本）。"""
    return {
        "table": item["table"],
        "source_id": item["source_id"],
        "dataset": item["dataset"],
        "dataset_title": item["dataset_title"],
        "n_rows": item["n_rows"],
        "n_cols": item["n_cols"],
        "columns": item["columns"][:12],
        "matched": hits,
        "score": round(score, 2),
    }


def table_info(table: str) -> dict | None:
    """看某张表：完整列名、数值列、行数与预览。"""
    name = (table or "").strip()
    if not name:
        return None
    if not name.startswith("t_"):
        name = _table_name(name)
    row = _meta_row(name)
    if not row:
        return None
    try:
        with _db_connect(readonly=True) as conn:
            preview = [dict(item) for item in conn.execute(
                f"SELECT * FROM {_quote(name)} LIMIT 3").fetchall()]
    except Exception:
        preview = []
    return {
        "table": row["table_name"],
        "source_id": row["source_id"],
        "dataset": row["dataset"],
        "dataset_title": row["dataset_title"],
        "n_rows": row["n_rows"],
        "n_cols": row["n_cols"],
        "columns": json.loads(row["columns"] or "[]"),
        "numeric_columns": json.loads(row["numeric_columns"] or "[]"),
        "is_html": bool(row["is_html"]),
        "source_file": row["source_file"],
        "preview": preview,
    }


_FORBIDDEN = re.compile(
    r"\b(attach|detach|pragma|vacuum|insert|update|delete|drop|create|alter|replace|"
    r"reindex|analyze|begin|commit|rollback|savepoint|release)\b",
    re.IGNORECASE,
)


def validate_readonly(sql: str) -> str:
    """只读校验：单条语句、只能 SELECT / WITH，且不含任何写/管理关键字。"""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return "SQL 不能为空。"
    if re.search(r";\s*\S", text):
        return "一次只能执行一条 SQL，请不要用分号拼接多条语句。"
    body = re.sub(r"'[^']*'|\"[^\"]*\"", " ", text)      # 抹掉字符串字面量再查关键字
    head = body.lstrip().split(None, 1)[0].lower() if body.strip() else ""
    if head not in ("select", "with", "explain"):
        return "这里只允许 SELECT / WITH 查询（表格数据是只读的）。"
    hit = _FORBIDDEN.search(body)
    if hit:
        return f"检测到不允许的关键字：{hit.group(0)}（表格数据只读）。"
    return ""


def query(sql: str, limit: int = 200) -> tuple[list[str], list[list], bool, str]:
    """执行只读查询，返回 (列名, 行, 是否被截断, 错误信息)。"""
    error = validate_readonly(sql)
    if error:
        return [], [], False, error
    if not DB_PATH.exists():
        return [], [], False, "表格索引还没建立，请先执行 python tables.py --build。"
    cap = max(1, min(int(limit or 200), 500))
    try:
        with _db_connect(readonly=True) as conn:
            cursor = conn.execute(sql)
            columns = [item[0] for item in (cursor.description or [])]
            rows = cursor.fetchmany(cap + 1)
        truncated = len(rows) > cap
        return columns, [list(row) for row in rows[:cap]], truncated, ""
    except sqlite3.Error as exc:
        return [], [], False, f"SQL 执行失败：{exc}"


def stats() -> dict:
    """规模统计（表数 / 行数 / 各数据集）。"""
    info = _read_build_info()
    if not info:
        return {"ok": False, "error": "索引未建立"}
    data = json.loads(info.get("stats") or "{}")
    data["ok"] = True
    data["built_at"] = info.get("built_at")
    data["db_bytes"] = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return data


def _match_dataset(name: str) -> str | None:
    """把用户给的名字归一成数据集 key（支持中文名与文件名片段）。"""
    text = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if text in DATASETS:
        return text
    for key, meta in DATASETS.items():
        if key in text or text in key:
            return key
        if meta["file"].split("-")[0].lower().replace("_", "") in text.replace("_", ""):
            return key
    aliases = {
        "table_query": ("表格查询", "单表查询", "tq"),
        "domain_ops": ("领域运算", "运算", "ops", "专业运算"),
        "multi_step": ("多步检索", "多步", "msr", "检索"),
    }
    for key, names in aliases.items():
        if any(alias in text for alias in names):
            return key
    return None


def list_sets() -> list[dict]:
    """三个数据集的规模（供工具与界面展示）。"""
    info = _read_build_info()
    stats_data = json.loads(info.get("stats") or "{}") if info else {}
    out = []
    for key, meta in DATASETS.items():
        row = (stats_data.get("datasets") or {}).get(key) or {}
        out.append({
            "key": key,
            "title": meta["title"],
            "desc": meta["desc"],
            "tables": row.get("tables", 0),
            "rows": row.get("rows", 0),
            "html_tables": row.get("html_tables", 0),
            "file": meta["file"],
            "ready": (TABLE_DATA_DIR / meta["file"]).exists(),
        })
    return out


def questions(dataset: str = "", limit: int = 10) -> list[dict]:
    """读取评测题（题干 + 参考答案，很多题没有答案）。"""
    key = _match_dataset(dataset) if dataset else None
    keys = [key] if key else list(DATASETS)
    out = []
    for item in keys:
        path = TABLE_DATA_DIR / DATASETS[item]["task"]
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in data[:limit]:
            out.append({"dataset": item, **row})
    return out


# --------------------------------------------------------------------------- #
# 问题分析（本地规则，零模型调用）：数据集定位 + 英文检索词 + 题型→SQL 写法 + 坑提示
# --------------------------------------------------------------------------- #
# 对标业务库那条链路的 analyze_query：先把「中文口语 → 该查哪张表、该用什么写法」讲清楚，
# 再让模型写 SQL。全部是本地规则，快、稳、不花钱。
_DATASET_KEYWORDS: dict[str, tuple[tuple[str, float], ...]] = {
    "multi_step": (
        ("咖啡", 2.0), ("拿铁", 2.0), ("卡布奇诺", 2.0), ("美式", 1.5), ("刷卡", 1.5), ("现金", 1.5),
        ("支付", 1.2), ("气象", 2.0), ("天气", 2.0), ("温度", 1.5), ("湿度", 1.5), ("风速", 1.5),
        ("降水", 1.5), ("季节", 1.5), ("新能源", 2.0), ("电动", 1.5), ("车型", 1.5), ("续航", 1.5),
        ("保险", 1.8), ("保费", 1.5), ("理赔", 1.5), ("地区生产总值", 2.0), ("gdp", 1.8),
        ("按月", 1.0), ("趋势", 1.0), ("coffee", 2.0), ("weather", 2.0), ("powertrain", 2.0),
    ),
    "domain_ops": (
        ("财报", 2.0), ("营收", 1.8), ("净收入", 2.0), ("净利润", 2.0), ("利差", 2.0), ("基点", 1.8),
        ("信用", 1.5), ("利率", 1.5), ("汇率", 1.5), ("占比", 1.5), ("百分比", 1.8), ("同比", 1.5),
        ("环比", 1.5), ("增长", 1.2), ("下降", 1.2), ("变化率", 2.0), ("上涨", 1.5), ("下跌", 1.5),
        ("电价", 2.0), ("煤", 1.5), ("石油", 1.5), ("资产", 1.2), ("负债", 1.5), ("权益", 1.5),
        ("假设", 0.8), ("并未发生", 1.8), ("摩根", 2.0), ("revenue", 2.0), ("spread", 2.0),
    ),
    "table_query": (
        ("哪一列", 1.5), ("哪列", 1.5), ("列名", 1.2), ("表头", 1.5), ("第一行", 1.5), ("单元格", 1.2),
        ("第几行", 1.5), ("第几列", 1.5), ("谓词", 2.0), ("主语", 1.8), ("宾语", 1.8), ("值是多少", 1.2),
        ("predicate", 2.0), ("subject", 1.8), ("object", 1.8), ("column", 1.8),
    ),
}

# 题型 → 推荐 SQL 写法（两个引擎都适用；方言差异由 describe_table 给出）
_QUESTION_TYPES: tuple[dict, ...] = (
    {"key": "ratio", "label": "占比 / 百分比 / 比重",
     "match": ("占比", "比重", "百分比", "比例", "百分数", "share", "percent", "比率"),
     "sql": "SUM(部分) * 100.0 / SUM(整体)，再用 ROUND(..., 2)",
     "tips": "分母取整表或题目指定范围；两个整数相除必须先 *100.0。"},
    {"key": "change", "label": "同比 / 环比 / 变化率 / 增长率",
     "match": ("同比", "环比", "变化率", "增长", "下降", "涨了", "跌了", "增加", "减少", "yoy", "mom"),
     "sql": "(v2 - v1) * 100.0 / v1；跨月对比可用 LAG(v) OVER (ORDER BY ym)",
     "tips": "先取到 v1 / v2 两个数（CASE WHEN 或子查询）再算比值；1 个基点 = 0.01%。"},
    {"key": "top", "label": "最大 / 最小 / 排名 / 前 N",
     "match": ("最多", "最少", "最高", "最低", "最大", "最小", "排名", "前几", "top"),
     "sql": "ORDER BY 数值 DESC/ASC LIMIT N",
     "tips": "先加业务过滤（如某类支付方式）再排序，别让无关行排到前面。"},
    {"key": "group", "label": "每个 / 各 / 按…分组统计",
     "match": ("每个", "各个", "分组", "分别", "按"),
     "sql": "GROUP BY 维度列 + SUM/COUNT/AVG，必要时 ORDER BY 聚合值 LIMIT N",
     "tips": "维度列若可能有重复写法（大小写/空格），先 SELECT DISTINCT 看一眼。"},
    {"key": "count", "label": "数量 / 多少 / 几次",
     # 注意不要用裸「多少」：中文里「是多少」是取值不是计数，会把事实查询误判成计数题
     "match": ("多少个", "多少条", "多少笔", "多少种", "多少位", "多少家", "多少张",
               "多少人", "多少次", "几个", "几条", "几笔", "几次", "数量", "个数", "count"),
     "sql": "COUNT(*)；问「多少种 / 多少人」用 COUNT(DISTINCT ...)",
     "tips": "col1 这类原表索引列不要当业务字段计数。"},
    {"key": "sum", "label": "合计 / 总额 / 一共多少钱",
     "match": ("合计", "总额", "一共", "总共", "总和", "总金额", "花了多少", "total"),
     "sql": "ROUND(SUM(金额列), 2)",
     "tips": "金额列已清洗成数字可直接 SUM；注意单位（列名里可能写着 million）。"},
    {"key": "average", "label": "平均 / 均值",
     "match": ("平均", "均值", "average", "avg", "mean"),
     "sql": "ROUND(AVG(数值列), 2)",
     "tips": "先 SELECT MIN/MAX 看一眼范围，避免异常值把均值带偏。"},
    {"key": "trend", "label": "按月 / 每月 / 趋势",
     "match": ("每月", "按月", "月度", "趋势", "走势", "逐月"),
     "sql": "GROUP BY substr(日期列, 1, 7)（MySQL 引擎用 LEFT(日期列, 7)）",
     "tips": "日期是 ISO 文本，可直接按字典序过滤；先聚合再谈趋势。"},
    {"key": "counterfactual", "label": "反事实假设（如果…没有发生）",
     "match": ("假设", "如果", "并未发生", "没有发生"),
     "sql": "把假设落到 SQL 里：先定位对应明细行，再从合计中剔除后重算",
     "tips": "不要对现成的合计数字直接做减法，否则答案不可复现。"},
    {"key": "lookup", "label": "事实查询（哪个 / 什么 / 某格的值）",
     "match": ("哪个", "什么", "哪一列", "第一行", "第几", "是多少", "内容"),
     "sql": "SELECT 列 FROM 表 WHERE 条件 LIMIT N（小表可直接 SELECT * LIMIT 3 看全貌）",
     "tips": "列名照抄 describe_table；两列 key-value 表按左列筛取右列。"},
)


def analyze_question(question: str, dataset: str = "") -> dict:
    """分析一个问题该怎么查表格库：定位数据集、给英文检索词、判题型、给写法与坑。

    纯本地规则（不调用模型、不查库），对应业务库那条链路的 analyze_query。
    """
    text = (question or "").strip()
    result: dict = {"question": text, "table_id": None, "datasets": [], "keywords": [],
                    "english": [], "types": [], "pitfalls": [], "next": []}
    if not text:
        return result

    # ① 问题里直接带表 id → 最高优先级
    id_match = re.search(r"\b([0-9a-f]{12,20})\b", text.lower())
    if id_match:
        name = _table_name(id_match.group(1))
        if _meta_row(name):
            result["table_id"] = id_match.group(1)
            result["next"].append(f"问题里带了表 id：直接 describe_table(table='{name}')，不必再召回")

    # ② 数据集判定（打分，可选参数直接加权）
    wanted = _match_dataset(dataset) if dataset else None
    lower = text.lower()
    scored = []
    for key, words in _DATASET_KEYWORDS.items():
        hits = [word for word, _weight in words if word in lower]
        score = sum(weight for word, weight in words if word in lower)
        if wanted == key:
            score += 5.0
        scored.append({"key": key, "title": DATASETS[key]["title"],
                       "score": round(score, 1), "hits": hits[:8]})
    scored.sort(key=lambda item: -item["score"])
    result["datasets"] = scored

    # ③ 中文术语 → 英文检索词（本地对照表）
    result["keywords"] = expand_terms(text)[:20]
    result["english"] = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)[:10]

    # ④ 题型判定（可同时命中多种，按定义顺序全部给出）
    for item in _QUESTION_TYPES:
        if any(word in lower for word in item["match"]):
            result["types"].append({"key": item["key"], "label": item["label"],
                                    "sql": item["sql"], "tips": item["tips"]})

    # ⑤ 按问题特征动态给坑提示
    if any(item["key"] in ("ratio", "change") for item in result["types"]):
        result["pitfalls"].append("比值一定要先乘 100.0 再除（SQLite 两个整数相除是整除，会得 0）")
    if re.search(r"[\u4e00-\u9fff]", text):
        result["pitfalls"].append("表里多是英文列名：列名一律照抄 describe_table 的返回，含空格/中文的加引号")
    result["pitfalls"].append("大表（上万行）先 WHERE / GROUP BY 聚合，不要 SELECT *")
    result["pitfalls"].append("答案里的数字必须来自 SQL 结果，不要心算")

    # ⑥ 建议的调用序列
    best = result["datasets"][0]
    hint = f"，dataset='{best['key']}'" if best["score"] > 0 else ""
    result["next"].append(f"find_table(question=问题原文{hint}) 定位候选表（可把第三步的英文检索词一起传）")
    result["next"].append("describe_table(table='t_xxxx') 看完整列名与数值列（写 SQL 前必看）")
    result["next"].append("query_tables(sql=...) 写只读 SQL 取数")
    return result


# --------------------------------------------------------------------------- #
# 四、命令行
# --------------------------------------------------------------------------- #
def _print_rows(columns: list[str], rows: list[list], truncated: bool) -> None:
    print(" | ".join(str(c) for c in columns))
    print("-" * 60)
    for row in rows:
        print(" | ".join("" if cell is None else str(cell) for cell in row))
    if truncated:
        print(f"...（结果被截断，只显示前 {len(rows)} 行，可用 LIMIT 精确控制）")


def main() -> None:
    parser = argparse.ArgumentParser(description="非结构化表格解析与查询（解析 非结构化数据/ 并建成 SQLite 索引）")
    parser.add_argument("--build", action="store_true", help="强制重建索引")
    parser.add_argument("--stats", action="store_true", help="打印规模统计")
    parser.add_argument("--sets", action="store_true", help="列出三个数据集")
    parser.add_argument("--find", metavar="QUESTION", help="按问题关键词召回候选表")
    parser.add_argument("--info", metavar="TABLE", help="看某张表的列与预览（如 t_2646e8725e97437）")
    parser.add_argument("--sql", metavar="SQL", help="执行只读 SQL")
    parser.add_argument("--questions", metavar="DATASET", nargs="?", const="", help="看评测题样例")
    parser.add_argument("--limit", type=int, default=5, help="条数上限")
    args = parser.parse_args()

    if not available():
        print(f"没有找到数据目录或数据文件：{TABLE_DATA_DIR}", file=sys.stderr)
        return

    need_build = args.build or not DB_PATH.exists()
    if need_build:
        info = build(force=True)
        print(f"索引已重建：{info['tables']} 张表 / {info['rows']} 行，用时 {info['seconds']}s，"
              f"文件 {DB_PATH}（{DB_PATH.stat().st_size/1024/1024:.1f} MB）")
    else:
        info = stats()

    if args.sets:
        for item in list_sets():
            print(f"  {item['key']:<12} {item['title']:<32} {item['tables']:>4} 张表 / "
                  f"{item['rows']:>6} 行（HTML {item['html_tables']}）  {item['desc']}")
    if args.stats or (not any([args.sets, args.find, args.info, args.sql, args.questions is not None])):
        info.setdefault("db_bytes", DB_PATH.stat().st_size if DB_PATH.exists() else 0)
        print(f"总计：{info.get('tables')} 张表 / {info.get('rows')} 行；"
              f"索引 {info.get('db_bytes', 0)/1024/1024:.1f} MB；建于 {info.get('built_at')}")
        for key, row in (info.get("datasets") or {}).items():
            print(f"  {DATASETS[key]['title']}：{row['tables']} 张表 / {row['rows']} 行"
                  f"（HTML {row['html_tables']}，跳过空块 {row['skipped_blocks']}）")
    if args.find:
        for item in find_tables(args.find, limit=args.limit):
            print(f"  {item['table']}  [{item['dataset_title']}]  {item['n_rows']} 行 × {item['n_cols']} 列"
                  f"  命中 {item['matched']}")
            print(f"      列：{'、'.join(str(c) for c in item['columns'])}")
    if args.info:
        detail = table_info(args.info)
        if not detail:
            print("没有找到这张表。")
        else:
            print(f"{detail['table']}（来源 {detail['source_file']}，{detail['dataset_title']}）")
            print(f"  {detail['n_rows']} 行 × {detail['n_cols']} 列；数值列：{detail['numeric_columns']}")
            print(f"  列名：{'、'.join(str(c) for c in detail['columns'])}")
            for row in detail["preview"]:
                print("   预览：", row)
    if args.sql:
        columns, rows, truncated, error = query(args.sql, limit=max(args.limit, 20))
        if error:
            print("查询失败：", error)
        else:
            _print_rows(columns, rows, truncated)
    if args.questions is not None:
        for item in questions(args.questions or "", limit=args.limit):
            answer = item.get("answer") or "（无参考答案）"
            print(f"  [{item['dataset']}] {item['id']}  {item['question']}")
            print(f"      参考答案：{answer}")


if __name__ == "__main__":
    main()
