#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""jiso 题集 NL→SQL 评测脚本（快速模式）。

对 `jiso/` 里的 680 道评测题（金融 279 / 医疗 210 / 通信 191）逐题：
  1. 组装提示词 = 数据库技能卡（skills/database/*.md）+ 实时真实表结构
  2. 单次 LLM 调用生成 SQL（不走向量检索、不带知识库样例，避免"泄题"）
  3. 生成 SQL 与参考答案 SQL 都在 MySQL 真实执行
  4. 比对结果集：行序无关（多重集）、列数一致、数值归一化

输出（reports/jiso_eval_<时间戳>/）：
  - details.jsonl  每题一行明细（问题 / 生成 SQL / 参考 SQL / 状态 / 耗时）
  - summary.md     总览报告（分库通过率 + 失败分类 + 错题样例）

用法：
  .venv\\Scripts\\python.exe eval_jiso.py --limit 10         # 试跑：每库前 10 题
  .venv\\Scripts\\python.exe eval_jiso.py --db finance       # 只跑金融库
  .venv\\Scripts\\python.exe eval_jiso.py                    # 全量 680 题
  .venv\\Scripts\\python.exe eval_jiso.py --resume --out reports/jiso_eval_xxx  # 断点续跑
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import date, datetime
from datetime import time as _time
from decimal import Decimal
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from core import agent as ag  # 复用项目配置：db_connect / build_llm / _validate_readonly / get_table_schema

ROOT = Path(__file__).resolve().parent.parent.parent

DATASETS = [
    {"key": "finance", "db": "financial_asset_management", "title": "金融",
     "file": "merged_problems1_task.json", "skill": "financial_asset_management.md"},
    {"key": "healthcare", "db": "healthcare_analytics_competition", "title": "医疗",
     "file": "merged_problems2_task.json", "skill": "healthcare_analytics_competition.md"},
    {"key": "telecom", "db": "telecom_operations_db", "title": "通信",
     "file": "merged_problems3_task.json", "skill": "telecom_operations_db.md"},
]

MAX_ROWS = 200000        # 单次查询最多拉取行数（超过视为 too_large，跳过判分）
SQL_TIMEOUT_MS = 30000   # 单条 SQL 执行上限（毫秒）

SYSTEM_TMPL = """你是资深 MySQL 8.0 数据分析师。请把用户的中文业务问题转写成一条【可直接执行】的 SQL 查询语句。

硬性要求（逐条遵守，尤其是第 3 条字段选择规则）：
1. 只输出 SQL 本身：不要解释、不要 Markdown 代码围栏、不要多余文字；只允许单条 SELECT / WITH 查询，禁止任何写操作。
2. 表名与列名必须以给定表结构为准，一个字都不能编造；中文字段值按技能卡口径书写。
3. 【输出字段的选择】严格按题目意图，不要自行增减：
   - 题目说"找出/列出/显示/查看【某对象】"（或"…的信息/详情"）且没有点名具体字段 → 输出该对象表的【全部字段】（SELECT *）；
     多表 JOIN 时输出主表全部字段（用 主表别名.*），不要用裸 *（避免带出其它表的列）；
   - 题目点名了字段（如"姓名和手机号""及其终止日期""和该比例"）→ 只输出点名字段（必要时加对象的主键列），不要多带其它列；
   - 统计/聚合类（"统计/按…统计/计算…的平均/数量/总和"）→ 只输出分组键列与聚合值列，不要 SELECT *。
4. 【数值与格式】聚合结果直接输出原值，不要套 ROUND()/FORMAT()/CAST()；从日期字段取年份用 YEAR(字段)（不要用 LEFT/SUBSTRING）。
5. 【写法安全】多表 JOIN 时 SELECT / WHERE / GROUP BY / ORDER BY 里的每个列名都加表别名前缀（避免 Column is ambiguous 错误）；
   使用 GROUP BY 时 SELECT 列表只能放分组键或聚合函数（避免 ONLY_FULL_GROUP_BY 错误）；
   只用常见的 MySQL 函数（如 LIKE、DATE_FORMAT），不要用 REGEXP_SUBSTR 这类参数复杂、容易写错的函数。
6. 【不要过度设计】不要添加题目未要求的过滤条件（例如自行加上 status<>3、is_active=1 之类"业务默认过滤"）；
   题目没要求"最新/最近一条"时，不要把"取最新记录"作为过滤条件；
   只在题目明确要求时才使用 ORDER BY / LIMIT（"前 N"或"最多"用 LIMIT N）。
7. 日期条件按字段实际类型书写（varchar 日期用 LIKE '2024%' 这类字符串匹配，date/datetime 用比较运算）；
   算百分比/变化率时写成 *100.0，避免整除截断。

----------- 数据库业务技能卡（口径 / 易错点 / 模板）-----------
{skill}

----------- 数据库真实表结构（{db}）-----------
{schema}
"""

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)```", re.S)
_START_RE = re.compile(r"(?is)\b(WITH|SELECT)\b")


# --------------------------------------------------------------------------- #
# SQL 提取与执行
# --------------------------------------------------------------------------- #
def _cut_top_level_semicolon(sql: str) -> str:
    """截断到引号外的第一个分号（字符串字面量 / 反引号标识符里的分号不算）。

    MySQL 字符串转义规则：\' 与 '' 都表示单引号本身。
    """
    quote = None
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            if ch == "\\" and quote == "'" and i + 1 < n:
                i += 2  # 跳过被反斜杠转义的字符
                continue
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    i += 2  # '' 转义
                    continue
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == ";":
            return sql[:i]
        i += 1
    return sql


def extract_sql(text: str) -> str:
    """从模型输出里提取 SQL：剥掉代码围栏与前后解释，取第一条 SELECT/WITH 到语句结束。

    没有出现 SELECT/WITH 关键字时返回空串（表示模型没产出 SQL）；
    末尾的说明文字通过"引号外的第一个分号"截掉，字符串里的分号不受影响。
    """
    if not text:
        return ""
    t = text.strip()
    m = _FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    m = _START_RE.search(t)
    if not m:
        return ""
    t = t[m.start():]
    return _cut_top_level_semicolon(t).strip()


def _keepalive(conn) -> None:
    """保活：连接断了尝试重连（pymysql 1.1 起 ping(reconnect=) 已弃用）。"""
    try:
        conn.ping()
    except Exception:  # noqa: BLE001
        try:
            conn.connect()
        except Exception:  # noqa: BLE001
            pass  # 重连失败则让随后的 execute 报错，归入该题的错误


def run_sql(conn, sql: str):
    """执行只读 SQL，返回 (列数, 行列表, 是否被截断)。异常原样抛出。"""
    _keepalive(conn)
    with conn.cursor() as cur:
        cur.execute("SET SESSION max_execution_time=%s", (SQL_TIMEOUT_MS,))
        cur.execute(sql)
        ncols = len(cur.description) if cur.description else 0
        rows = cur.fetchmany(MAX_ROWS)
        truncated = len(rows) >= MAX_ROWS
    return ncols, list(rows), truncated


# --------------------------------------------------------------------------- #
# 结果集比对（行序无关；数值归一化）
# --------------------------------------------------------------------------- #
def _dec_str(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def _cell_key(v):
    """把单元格值归一化成可哈希的 (类型, 规范字符串)，抹平 123 / 123.0 这类差异。"""
    if v is None:
        return ("null", "")
    if isinstance(v, bool):
        return ("num", "1" if v else "0")
    if isinstance(v, Decimal):
        return ("num", _dec_str(v))
    if isinstance(v, int):
        return ("num", str(v))
    if isinstance(v, float):
        return ("num", _dec_str(Decimal(str(v))))
    if isinstance(v, datetime):
        base = v.strftime("%Y-%m-%d %H:%M:%S")
        return ("dt", base + (f".{v.microsecond:06d}" if v.microsecond else ""))
    if isinstance(v, date):
        return ("dt", v.strftime("%Y-%m-%d"))
    if isinstance(v, _time):
        base = v.strftime("%H:%M:%S")
        return ("dt", base + (f".{v.microsecond:06d}" if v.microsecond else ""))
    if isinstance(v, (bytes, bytearray)):
        return ("str", bytes(v).decode("utf-8", "replace"))
    return ("str", str(v))


def result_counter(rows) -> Counter:
    return Counter(tuple(_cell_key(v) for v in row) for row in rows)


# --------------------------------------------------------------------------- #
# LLM 调用
# --------------------------------------------------------------------------- #
def ask_llm(llm, system_prompt: str, question: str, retries: int = 3) -> str:
    """单次生成 SQL；失败重试。返回提取后的 SQL（可能为空串）。"""
    last_err = None
    for i in range(retries):
        try:
            resp = llm.invoke([SystemMessage(content=system_prompt),
                               HumanMessage(content=question)])
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            return extract_sql(content)
        except Exception as exc:  # noqa: BLE001 —— 网络 / 限流等
            last_err = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"LLM 调用失败（重试 {retries} 次）：{last_err}")


# --------------------------------------------------------------------------- #
# 单题评测
# --------------------------------------------------------------------------- #
def eval_task(llm, conn, ds_title: str, db_name: str, task: dict, system_prompt: str) -> dict:
    t0 = time.time()
    rec = {
        "db": db_name, "title": ds_title, "id": task["id"], "problem": task["problem"],
        "gen_sql": "", "ref_sql": task["sql"].strip(), "status": "", "detail": "", "elapsed": 0.0,
    }

    # ① 生成 SQL
    try:
        gen_sql = ask_llm(llm, system_prompt, task["problem"])
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "api_error"
        rec["detail"] = str(exc)[:400]
        rec["elapsed"] = round(time.time() - t0, 1)
        return rec
    rec["gen_sql"] = gen_sql
    if not gen_sql:
        rec["status"] = "empty"
        rec["detail"] = "模型没有输出可识别的 SQL"
        rec["elapsed"] = round(time.time() - t0, 1)
        return rec

    # ② 参考 SQL 先执行（失败说明题集 / 数据有问题）
    try:
        ref_body = ag._validate_readonly(task["sql"])
        ref_ncols, ref_rows, ref_trunc = run_sql(conn, ref_body)
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "ref_error"
        rec["detail"] = f"参考 SQL 执行失败：{exc}"[:400]
        rec["elapsed"] = round(time.time() - t0, 1)
        return rec

    # ③ 生成 SQL 安全校验 + 执行
    try:
        gen_body = ag._validate_readonly(gen_sql)
    except ValueError as exc:
        rec["status"] = "gen_sql_error"
        rec["detail"] = f"只读校验未通过：{exc}"[:400]
        rec["elapsed"] = round(time.time() - t0, 1)
        return rec
    try:
        gen_ncols, gen_rows, gen_trunc = run_sql(conn, gen_body)
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "gen_sql_error"
        rec["detail"] = f"执行失败：{exc}"[:400]
        rec["elapsed"] = round(time.time() - t0, 1)
        return rec

    # ④ 比对
    if ref_trunc or gen_trunc:
        rec["status"] = "too_large"
        rec["detail"] = f"结果集超过 {MAX_ROWS} 行，跳过判分"
    elif gen_ncols != ref_ncols:
        rec["status"] = "wrong"
        rec["detail"] = f"列数不同：生成 {gen_ncols} 列 vs 参考 {ref_ncols} 列"
    elif result_counter(gen_rows) == result_counter(ref_rows):
        rec["status"] = "pass"
        rec["detail"] = f"{len(gen_rows)} 行一致"
    else:
        rec["status"] = "wrong"
        rec["detail"] = f"行集不同：生成 {len(gen_rows)} 行 vs 参考 {len(ref_rows)} 行"
    rec["elapsed"] = round(time.time() - t0, 1)
    return rec


# --------------------------------------------------------------------------- #
# 汇总报告
# --------------------------------------------------------------------------- #
STATUS_ORDER = ["pass", "wrong", "gen_sql_error", "empty", "api_error", "ref_error", "too_large"]
STATUS_ZH = {
    "pass": "✅ 通过", "wrong": "❌ 结果不一致", "gen_sql_error": "⚠️ SQL 执行失败",
    "empty": "⚠️ 未产出 SQL", "api_error": "⚠️ 模型调用失败",
    "ref_error": "🔧 参考 SQL 失败", "too_large": "📦 结果集过大",
}


def write_summary(out_dir: Path, details_path: Path, started: str, elapsed_total: float) -> None:
    records = []
    for line in details_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    by_db: dict[str, list[dict]] = {}
    for r in records:
        by_db.setdefault(r["db"], []).append(r)

    lines = [
        "# jiso 题集 NL→SQL 评测报告（快速模式）",
        "",
        f"- 运行时间：{started}，总耗时 {elapsed_total:.0f} 秒",
        f"- 模型：{ag.provider_info().get('provider')} / {ag.provider_info().get('model')}",
        f"- 判分口径：生成 SQL 与参考 SQL 在 MySQL 真实执行，结果集比对（行序无关、列数一致、数值归一化）",
        "",
        "## 总览",
        "",
        "| 库 | 题数 | 通过 | 通过率 | 结果不一致 | SQL失败 | 未产出 | 其它 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def _count(items, status) -> int:
        return sum(1 for x in items if x["status"] == status)

    total_all = len(records)
    pass_all = _count(records, "pass")
    for db in [d["db"] for d in DATASETS]:
        items = by_db.get(db, [])
        if not items:
            continue
        n = len(items)
        p = _count(items, "pass")
        rest = n - p - _count(items, "wrong") - _count(items, "gen_sql_error") - _count(items, "empty")
        lines.append(
            f"| {db} | {n} | {p} | {p / n * 100:.1f}% | {_count(items, 'wrong')} | "
            f"{_count(items, 'gen_sql_error')} | {_count(items, 'empty')} | {rest} |"
        )
    lines.append(
        f"| **合计** | **{total_all}** | **{pass_all}** | "
        f"**{pass_all / total_all * 100:.1f}%** | | | | |"
        if total_all else "| **合计** | 0 | 0 | - | | | | |"
    )

    lines += ["", "## 失败分类统计", ""]
    for st in STATUS_ORDER:
        c = _count(records, st)
        if c:
            lines.append(f"- {STATUS_ZH.get(st, st)}：{c} 题")
    api = _count(records, "api_error")
    ref = _count(records, "ref_error")
    if api or ref:
        lines.append("")
        if ref:
            lines.append(f"> 注：{ref} 题是参考答案本身执行失败（题集/数据问题），不计入模型失误。")
        if api:
            lines.append(f"> 注：{api} 题因模型调用失败未能判分。")

    lines += ["", "## 错题样例（最多 12 条，含结果不一致与 SQL 失败）", ""]
    bad = [r for r in records if r["status"] in ("wrong", "gen_sql_error", "empty")]
    for r in bad[:12]:
        lines += [
            f"### [{r['title']}] #{r['id']} {r['problem'][:80]}",
            "",
            f"- 状态：{STATUS_ZH.get(r['status'], r['status'])}（{r['detail']}）",
            f"- 生成：`{r['gen_sql'][:300]}`",
            f"- 参考：`{r['ref_sql'][:300]}`",
            "",
        ]

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="jiso 题集 NL→SQL 评测（快速模式）")
    ap.add_argument("--db", choices=["all", "finance", "healthcare", "telecom"], default="all",
                    help="只评测某个库（默认 all）")
    ap.add_argument("--limit", type=int, default=0, help="每库最多评测多少题（0=全量）")
    ap.add_argument("--resume", action="store_true", help="跳过明细文件里已完成的题（断点续跑）")
    ap.add_argument("--out", default="", help="输出目录（默认 reports/jiso_eval_<时间戳>）")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "reports" / f"jiso_eval_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    details_path = out_dir / "details.jsonl"

    done = set()
    if args.resume and details_path.exists():
        for line in details_path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                done.add((d["db"], str(d["id"])))
            except json.JSONDecodeError:
                pass
        print(f"[resume] 已完成 {len(done)} 题，将跳过")

    llm = ag.build_llm()
    info = ag.provider_info()
    print(f"[eval] 模型：{info.get('provider')} / {info.get('model')}")
    print(f"[eval] 输出目录：{out_dir}")

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    t_all = time.time()
    plan = [d for d in DATASETS if args.db in ("all", d["key"])]

    for ds in plan:
        tasks = json.loads((ROOT / "jiso" / ds["file"]).read_text(encoding="utf-8"))
        if args.limit:
            tasks = tasks[:args.limit]
        tasks = [t for t in tasks if (ds["db"], str(t["id"])) not in done]
        if not tasks:
            print(f"=== [{ds['title']}] 没有需要评测的题，跳过 ===")
            continue

        skill = (ROOT / "skills" / "database" / ds["skill"]).read_text(encoding="utf-8")
        schema = ag.get_table_schema.invoke({"table": "", "database": ds["db"]})
        if "不存在" in schema or "失败" in schema[:50]:
            print(f"[X] 读取 {ds['db']} 表结构失败：{schema[:200]}")
            continue
        system_prompt = SYSTEM_TMPL.format(skill=skill, schema=schema, db=ds["db"])

        conn = ag.db_connect(ds["db"])
        print(f"\n=== [{ds['title']}库] 开始评测 {len(tasks)} 题 ===")
        n_pass = 0
        try:
            for i, task in enumerate(tasks, 1):
                rec = eval_task(llm, conn, ds["title"], ds["db"], task, system_prompt)
                with open(details_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if rec["status"] == "pass":
                    n_pass += 1
                flag = "PASS" if rec["status"] == "pass" else rec["status"].upper()
                print(f"  [{i}/{len(tasks)}] #{task['id']} {flag} ({rec['elapsed']:.1f}s)"
                      + ("" if rec["status"] == "pass" else f"  {rec['detail'][:80]}"))
        finally:
            conn.close()
        print(f"=== [{ds['title']}库] 完成：{n_pass}/{len(tasks)} 通过 "
              f"（{n_pass / len(tasks) * 100:.1f}%）===")

    elapsed = time.time() - t_all
    write_summary(out_dir, details_path, started, elapsed)
    print(f"\n[eval] 全部完成，耗时 {elapsed:.0f} 秒")
    print(f"[eval] 明细：{details_path}")
    print(f"[eval] 报告：{out_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
