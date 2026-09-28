"""Excel / CSV 等**真实表格文件**的解析器（services/spreadsheet.py）。

改造前 tables.py 只认「非结构化数据/」下三个硬编码 .md 里的 Markdown / HTML 表格，
把 *.xlsx / *.csv 丢进目录也解析不出任何东西（实测 build 得到 0 张表）。
这个模块补上「按后缀解析真实表格文件」这一环，产出与 tables.parse_table_block
**同构**的结果（{columns, rows, numeric, is_html}），直接复用既有入库与查询链路：

    文件 → spreadsheet.parse_file() → tables.build() → tables.sqlite3 → query_tables（Agent）

设计取舍：
- 单元格先统一转成**字符串**再交给 tables 的 detect_numeric_columns / coerce_rows，
  数值判定规则就只有一份（不会出现「Excel 里算数值、CSV 里算文本」的分裂）。
- 日期时间一律转成 ISO 字符串：SQLite 没有日期类型，转成文本后仍能比较和 LIKE。
- 一个 Excel 的多个 sheet 拆成多张表，表名可读（t_销售明细_xlsx_月度销售）。

CLI：python -m services.datasource.spreadsheet <文件或目录>   # 打印解析结果，不写库
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

try:                                    # 包式运行：python -m services.datasource.spreadsheet
    from services.datasource import tables
except ModuleNotFoundError:             # 直接运行：python -m services.datasource.spreadsheet
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.datasource import tables

# 支持的文件后缀（.txt 走分隔符探测，只在确实像表格时才收）
SUFFIX_EXCEL = {".xlsx", ".xlsm", ".ods"}
SUFFIX_LEGACY = {".xls"}
SUFFIX_DELIM = {".csv", ".tsv", ".txt"}
SUFFIX_JSON = {".json", ".jsonl", ".ndjson"}
SUFFIX_PARQUET = {".parquet", ".pq", ".feather"}
SUFFIX_SQLITE = {".sqlite", ".sqlite3", ".db"}
SUFFIX_XML = {".xml"}
SUPPORTED_SUFFIXES = (SUFFIX_EXCEL | SUFFIX_LEGACY | SUFFIX_DELIM | SUFFIX_JSON |
                      SUFFIX_PARQUET | SUFFIX_SQLITE | SUFFIX_XML)

# 读盘编码顺序：国内 Excel 导出的 CSV 多为 GBK，带 BOM 的 UTF-8 也要先试
ENCODINGS = ("utf-8-sig", "gb18030", "utf-8", "big5", "latin-1")

MAX_ROWS = int(os.getenv("TABLE_FILE_MAX_ROWS", "200000"))     # 单张表最多收多少行
MAX_COLS = int(os.getenv("TABLE_FILE_MAX_COLS", "200"))        # 单张表最多收多少列
MAX_CELL_CHARS = 500                                           # 单元格文本上限（防止一个备注撑爆 blob）


class SpreadsheetError(Exception):
    """文件读不动（缺依赖 / 损坏 / 加密）——调用方据此跳过并记一笔原因。"""


def supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def discover(directory: str | Path) -> list[Path]:
    """列出目录里的表格文件（不含子目录里的评测 .md；顺序稳定便于重建比对）。"""
    base = Path(directory)
    if not base.is_dir():
        return []
    return sorted((p for p in base.iterdir()
                   if p.is_file() and supported(p) and not p.name.startswith("~$")),
                  key=lambda p: p.name.lower())


def _clean_cell(value) -> str:
    """单元格 → 字符串：空值、NaN、日期各有各的归一方式。"""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:          # NaN
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):                               # numpy 标量
        try:
            value = value.item()
        except Exception:
            value = str(value)
    text = str(value).strip()
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return text


def _read_text(path: Path) -> str:
    for encoding in ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _sniff_delimiter(sample: str, default: str = ",") -> str:
    """按第一行出现的次数猜分隔符（.txt 可能是逗号也可能是制表符）。"""
    first = sample.splitlines()[0] if sample else ""
    counts = {"\t": first.count("\t"), ",": first.count(","),
              ";": first.count(";"), "|": first.count("|")}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] > 0 else default


def _drop_title_row(rows: list[list[str]]) -> list[list[str]]:
    """丢掉 Excel 常见的「大标题行」。

    真实表格经常是：第 1 行一个合并大标题（"重庆财经学院2026-2027学年贫困生认定公示名单"），
    第 2 行才是真正的列名。直接拿第 1 行当表头的话，列名会变成那句标题，
    真正的表头反而被当成数据行——整张表就没法查了。
    判据：首行几乎只有一格有字，或首行有效格数远少于第二行。
    """
    if len(rows) < 2:
        return rows

    def non_empty(row: list[str]) -> int:
        return sum(1 for cell in row if cell)

    first, second = non_empty(rows[0]), non_empty(rows[1])
    if first <= 1 or (second and first * 2 <= second):
        return rows[1:]
    return rows


def _looks_like_header(row: list[str]) -> bool:
    """首行是不是表头：只要有一个非空且非纯数字的单元格，就当它是列名。"""
    if not row:
        return False
    cleaned = [cell for cell in row if cell]
    if not cleaned:
        return False
    return any(not re.fullmatch(r"-?\d+(\.\d+)?", cell) for cell in cleaned)


def _finish(headers: list[str], rows: list[list]) -> dict | None:
    """复用 tables 的归一逻辑，产出与 Markdown 表同构的结果。"""
    if not rows:
        return None
    width = max([len(headers)] + [len(r) for r in rows[:200]])
    width = min(max(width, 1), MAX_COLS)
    columns = tables.normalize_columns(headers, width)
    normalized = tables.normalize_rows(rows, width)
    numeric = tables.detect_numeric_columns(normalized, width)
    return {
        "columns": columns,
        "rows": tables.coerce_rows(normalized, numeric),
        "numeric": numeric,
        "is_html": False,
    }


def _empty_table(headers: list[str]) -> dict | None:
    """保留空 SQLite 表的结构，让模型能识别并在后续数据写入后直接查询。"""
    if not headers:
        return None
    columns = tables.normalize_columns(headers, min(len(headers), MAX_COLS))
    return {"columns": columns, "rows": [], "numeric": [False] * len(columns), "is_html": False}


def _parse_delimited(path: Path) -> Iterator[tuple[str, dict]]:
    text = _read_text(path)
    if not text.strip():
        return
    delimiter = "\t" if path.suffix.lower() == ".tsv" else _sniff_delimiter(text, ",")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [[_clean_cell(cell) for cell in row] for row in reader]
    rows = [row for row in rows if any(cell for cell in row)]     # 丢掉全空行
    if not rows:
        return
    rows = _drop_title_row(rows)                                  # 丢掉可能的大标题行
    headers = rows[0] if _looks_like_header(rows[0]) else []
    body = rows[1:] if headers else rows
    table = _finish(headers, body[:MAX_ROWS])
    if table:
        yield path.stem, table


def _parse_excel(path: Path) -> Iterator[tuple[str, dict]]:
    try:
        import pandas as pd
    except ImportError as exc:                    # 理论上不会发生：pandas 是既有依赖
        raise SpreadsheetError(f"缺少 pandas，无法读取 Excel：{exc}") from exc
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=object, header=None)
    except ImportError as exc:                     # .xls 需要 xlrd；缺失时给明确指引
        raise SpreadsheetError(f"读取 {path.name} 需要额外依赖（{exc}）；"
                               "老版 .xls 请另存为 .xlsx") from exc
    except Exception as exc:
        raise SpreadsheetError(f"读取 {path.name} 失败：{exc}") from exc

    for sheet_name, frame in (sheets or {}).items():
        rows = [[_clean_cell(cell) for cell in row]
                for row in frame.itertuples(index=False, name=None)]
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        rows = _drop_title_row(rows)
        headers = rows[0] if _looks_like_header(rows[0]) else []
        body = rows[1:] if headers else rows
        table = _finish(headers, body[:MAX_ROWS])
        if not table:
            continue
        # sheet 名一律带上：既让表名可读，也让「按 sheet 名找表」能召回
        # （只在工作簿只有一个 sheet 时省略的话，问「月度销售」会一条都找不到）
        source_id = f"{path.stem}#{sheet_name}"
        yield source_id, table


def _records_table(records: list[dict]) -> dict | None:
    """对象列表规整成一张表，嵌套值保留为 JSON 文本以免静默丢字段。"""
    if not records:
        return None
    columns: list[str] = []
    for record in records:
        for key in record:
            key = str(key)
            if key not in columns:
                columns.append(key)
            if len(columns) >= MAX_COLS:
                break
    rows = []
    for record in records[:MAX_ROWS]:
        row = []
        for column in columns:
            value = record.get(column, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            row.append(_clean_cell(value))
        rows.append(row)
    return _finish(columns, rows)


def _parse_json(path: Path) -> Iterator[tuple[str, dict]]:
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            raw = [json.loads(line) for line in _read_text(path).splitlines() if line.strip()]
        else:
            raw = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise SpreadsheetError(f"JSON 格式错误：{exc}") from exc
    if isinstance(raw, dict):
        for key in ("data", "records", "items", "rows", "result"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raw = [{"value": raw}]
    records = [item if isinstance(item, dict) else {"value": item} for item in raw]
    table = _records_table(records)
    if table:
        yield path.stem, table


def _parse_parquet(path: Path) -> Iterator[tuple[str, dict]]:
    try:
        import pandas as pd
        frame = pd.read_feather(path) if path.suffix.lower() == ".feather" else pd.read_parquet(path)
    except ImportError as exc:
        raise SpreadsheetError(f"读取 {path.name} 需要 pyarrow：{exc}") from exc
    except Exception as exc:
        raise SpreadsheetError(f"读取 {path.name} 失败：{exc}") from exc
    rows = [[_clean_cell(value) for value in row] for row in frame.itertuples(index=False, name=None)]
    table = _finish([str(x) for x in frame.columns], rows[:MAX_ROWS])
    if table:
        yield path.stem, table


def _parse_sqlite(path: Path) -> Iterator[tuple[str, dict]]:
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise SpreadsheetError(f"打开 SQLite 数据库失败：{exc}") from exc
    try:
        names = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        for (name,) in names:
            quoted = '"' + str(name).replace('"', '""') + '"'
            try:
                cur = conn.execute(f"SELECT * FROM {quoted} LIMIT {MAX_ROWS}")
                headers = [str(col[0]) for col in (cur.description or [])]
                rows = [[_clean_cell(value) for value in row] for row in cur.fetchall()]
                table = _finish(headers, rows) or _empty_table(headers)
                if table:
                    yield f"{path.stem}#{name}", table
            except sqlite3.Error as exc:
                print(f"[spreadsheet] 跳过 SQLite 表 {name}：{exc}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def _parse_xml(path: Path) -> Iterator[tuple[str, dict]]:
    try:
        root = ET.fromstring(path.read_bytes())
    except ET.ParseError as exc:
        raise SpreadsheetError(f"XML 格式错误：{exc}") from exc
    children = list(root)
    nodes = children if children else [root]
    records: list[dict] = []
    for node in nodes:
        record = {f"@{key}": value for key, value in node.attrib.items()}
        nested = list(node)
        if nested:
            for child in nested:
                key = child.tag.rsplit("}", 1)[-1]
                value = child.text or ""
                if list(child):
                    value = ET.tostring(child, encoding="unicode")
                record[key] = value
        else:
            record[node.tag.rsplit("}", 1)[-1]] = node.text or ""
        records.append(record)
    table = _records_table(records)
    if table:
        yield path.stem, table


def parse_file(path: str | Path) -> Iterator[tuple[str, dict]]:
    """解析单个文件，逐张产出 (source_id, 表格字典)。读不动就抛 SpreadsheetError。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in SUFFIX_EXCEL or suffix in SUFFIX_LEGACY:
        yield from _parse_excel(path)
    elif suffix in SUFFIX_DELIM:
        yield from _parse_delimited(path)
    elif suffix in SUFFIX_JSON:
        yield from _parse_json(path)
    elif suffix in SUFFIX_PARQUET:
        yield from _parse_parquet(path)
    elif suffix in SUFFIX_SQLITE:
        yield from _parse_sqlite(path)
    elif suffix in SUFFIX_XML:
        yield from _parse_xml(path)
    else:
        raise SpreadsheetError(f"不支持的文件类型：{suffix}")


def parse_directory(directory: str | Path) -> Iterator[tuple[str, str, dict]]:
    """解析整个目录，逐张产出 (文件名, source_id, 表格字典)；坏文件只记录不中断。"""
    for path in discover(directory):
        try:
            for source_id, table in parse_file(path):
                yield path.name, source_id, table
        except SpreadsheetError as exc:
            print(f"[spreadsheet] 跳过 {path.name}：{exc}", file=sys.stderr, flush=True)
        except Exception as exc:                  # 单个文件炸了不能拖垮整次构建
            print(f"[spreadsheet] 跳过 {path.name}：{type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)


def _selftest() -> int:
    """离线自检：不依赖任何外部文件，自己造数据自己验。"""
    import tempfile

    ok, ng = 0, 0

    def check(name: str, got, want) -> None:
        nonlocal ok, ng
        if got == want:
            ok += 1
            print(f"  [OK] {name}")
        else:
            ng += 1
            print(f"  [NG] {name}  期望={want!r} 实际={got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # ① CSV（UTF-8，带 BOM）
        csv_file = tmp / "销售.csv"
        csv_file.write_text("\ufeff月份,销售额,区域\n2024-01,120000.5,华东\n"
                            "2024-02,135800,华南\n2024-03,98000.25,华北\n", encoding="utf-8")
        items = list(parse_file(csv_file))
        check("CSV 解析出 1 张表", len(items), 1)
        source_id, table = items[0]
        check("CSV 列名去掉了 BOM", table["columns"][0], "月份")
        check("CSV 行数", len(table["rows"]), 3)
        check("销售额被判为数值列", table["numeric"][1], True)
        check("区域不是数值列", table["numeric"][2], False)
        check("数值列转成了 float", table["rows"][0][1], 120000.5)

        # ② CSV（GBK 编码，国内 Excel 导出的常见形态）
        gbk_file = tmp / "客户名单.csv"
        gbk_file.write_text("客户编号,客户名称,等级\n1,张三,VIP\n2,李四,普通\n", encoding="gbk")
        _sid, tbl = list(parse_file(gbk_file))[0]
        check("GBK 编码能读", tbl["rows"][0][1], "张三")

        # ③ TSV
        tsv_file = tmp / "指标.tsv"
        tsv_file.write_text("指标\t数值\n活跃用户\t12000\n留存率\t0.63\n", encoding="utf-8")
        _sid, tbl = list(parse_file(tsv_file))[0]
        check("TSV 按制表符切分", tbl["columns"], ["指标", "数值"])

        # ④ Excel（多 sheet → 多张表）
        try:
            import pandas as pd
            xlsx = tmp / "销售明细.xlsx"
            with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
                pd.DataFrame({"月份": ["2024-01", "2024-02"], "销售额": [1.5, 2.5],
                              "区域": ["华东", "华南"]}).to_excel(
                    writer, sheet_name="月度销售", index=False)
                pd.DataFrame({"产品": ["A", "B"], "库存": [320, 155]}).to_excel(
                    writer, sheet_name="库存", index=False)
            parsed = list(parse_file(xlsx))
            check("Excel 两个 sheet → 两张表", len(parsed), 2)
            check("sheet 名进 source_id", parsed[0][0], "销售明细#月度销售")
            check("Excel 数值列生效", parsed[0][1]["rows"][0][1], 1.5)
            check("第二张表内容", parsed[1][1]["columns"], ["产品", "库存"])
        except ImportError:
            print("  [跳过] 未安装 openpyxl，Excel 用例未验证")

        # ⑤ 没有表头 → 自动生成列名
        no_header = tmp / "无表头.csv"
        no_header.write_text("1,2\n3,4\n", encoding="utf-8")
        _sid, tbl = list(parse_file(no_header))[0]
        check("无表头自动生成列名", tbl["columns"], ["col1", "col2"])
        check("无表头时首行当数据", len(tbl["rows"]), 2)

        # ⑥ 空文件 / 非法类型
        empty = tmp / "空.csv"
        empty.write_text("", encoding="utf-8")
        check("空文件产出 0 张表", len(list(parse_file(empty))), 0)
        try:
            list(parse_file(tmp / "说明.docx"))
            check("非法后缀应报错", "未报错", "SpreadsheetError")
        except SpreadsheetError:
            check("非法后缀应报错", "SpreadsheetError", "SpreadsheetError")

        # ⑦ 目录发现
        found = discover(tmp)
        # 目录里此刻有：销售.csv / 客户名单.csv / 指标.tsv / 销售明细.xlsx / 无表头.csv / 空.csv
        check("目录能发现全部 6 个表格文件", len(found), 6)

    print(f"\n自检：{ok} 项通过，{ng} 项失败")
    return 1 if ng else 0


def main(argv: list[str]) -> int:
    if not argv:
        return _selftest()
    target = Path(argv[0])
    files = [target] if target.is_file() else discover(target)
    if not files:
        print(f"没有在 {target} 找到可解析的表格文件（支持 "
              f"{'/'.join(sorted(SUPPORTED_SUFFIXES))}）")
        return 1
    total = 0
    for path in files:
        try:
            for source_id, table in parse_file(path):
                total += 1
                print(f"\n=== {path.name} · {source_id} ===")
                print("列：", "、".join(table["columns"]))
                print("数值列：", "、".join(c for c, flag in
                                            zip(table["columns"], table["numeric"]) if flag) or "（无）")
                print(f"行数：{len(table['rows'])}")
                for row in table["rows"][:3]:
                    print("   ", row)
        except SpreadsheetError as exc:
            print(f"\n=== {path.name} ===\n  跳过：{exc}")
    print(f"\n共 {total} 张表")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
