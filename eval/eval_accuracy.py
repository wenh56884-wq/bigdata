# -*- coding: utf-8 -*-
"""问答准确率评测：跑真实 Agent（含工具调用），用**查库得到的权威答案**自动判分。

用法（在 app/ 目录下）：
    python eval/eval_accuracy.py                 # 全部用例
    python eval/eval_accuracy.py --only sql-finance
    python eval/eval_accuracy.py --ids F1,F2,H3
    python eval/eval_accuracy.py --limit 10
    python eval/eval_accuracy.py --json report.json

判分方式（不靠 LLM 打分，保证可复现）：
    数值题：从回答里抽取数字（支持千分位、万/亿单位），与**直连数据库算出的真值**
            逐项比对，容差 max(0.5, 真值*0.5%)
    文本题：回答里必须包含期望片段之一（去空格、忽略大小写）
    另附：回答不得为空、不得是"没查到/数据不可用"这类空转回复

每条用例一个独立 thread_id，避免记忆污染；失败用例会打印回答摘要，便于定位。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pymysql

from core.agent import ChatService
from services.ml_forecast import db_config
from eval.qa_cases import CASES, Case

TOLERANCE_REL = 0.005          # 数值容差：0.5%
TOLERANCE_ABS = 0.5
DEAD_ANSWERS = ("没有查到", "没查到", "无法查询", "数据不可用", "SQL 解释：执行失败",
                "查不到", "未能获取", "没有找到")

_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(亿|万|千|%)?")
_UNIT = {"亿": 1e8, "万": 1e4, "千": 1e3, "%": 1.0}


# --------------------------------------------------------------------------- #
# 真值计算：直连数据库（权威来源，不经过模型）
# --------------------------------------------------------------------------- #
def truth_value(case: Case):
    """执行 truth_sql 得到标准答案（单值）；失败返回 None。

    Decimal 会转成 float——既不丢后续的数值比对精度，也保证报告能 JSON 序列化。
    """
    if not (case.db and case.truth_sql):
        return None
    conn = pymysql.connect(database=case.db, **db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(case.truth_sql)
            row = cur.fetchone()
            if not row:
                return None
            value = row[0]
            return float(value) if hasattr(value, "as_tuple") else value
    finally:
        conn.close()


def extract_numbers(text: str) -> list[float]:
    """抽取回答里的数字：处理千分位与万/亿单位（% 视作单位但不缩放）。"""
    values: list[float] = []
    for match in _NUM_RE.finditer(text or ""):
        raw = match.group(1).replace(",", "").replace("，", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = match.group(2)
        if unit in _UNIT:
            value *= _UNIT[unit]
        values.append(value)
    return values


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def number_matches(answer: str, truth) -> tuple[bool, str]:
    """数值判分：真值或其常见写法（万元/亿、四舍五入）是否出现在回答里。"""
    try:
        target = float(truth)
    except (TypeError, ValueError):
        # 文本型真值：直接包含即可
        ok = str(truth) in answer
        return ok, f"文本真值 {truth!r}"
    candidates = {target, round(target, 2), round(target, 1), round(target),
                  target / 1e4, round(target / 1e4, 2), round(target / 1e4, 1),
                  target / 1e8, round(target / 1e8, 2)}
    found = extract_numbers(answer)
    best = None
    for candidate in candidates:
        for value in found:
            diff = abs(value - candidate)
            if diff <= max(TOLERANCE_ABS, abs(candidate) * TOLERANCE_REL):
                return True, f"命中 {value} ≈ {candidate}"
            if best is None or diff < best[0]:
                best = (diff, value, candidate)
    hint = f"最接近 {best[1]} vs 真值 {best[2]}（差 {best[0]:,.2f}）" if best else "回答里没找到数字"
    return False, hint


def judge(case: Case, answer: str, truth) -> tuple[bool, str]:
    text = answer or ""
    if not text.strip():
        return False, "回答为空"
    lowered = _norm(text)
    if any(_norm(word) in lowered for word in DEAD_ANSWERS) and not case.expect_text:
        return False, "回答是‘没查到’类型的空转回复"
    if case.check:
        return case.check(text, list(case.expect_text))
    if truth is not None:
        return number_matches(text, truth)
    for pattern in case.expect_regex:      # 说法多变时用正则，避免"没说固定措辞就算错"
        if re.search(pattern, text or ""):
            return True, f"命中正则：{pattern}"
    hits = [word for word in case.expect_text if _norm(word) in lowered]
    if case.expect_regex:
        return False, f"未命中任一正则：{case.expect_regex}"
    if case.expect_text and not hits:
        return False, f"缺关键词（任一即可）：{case.expect_text}"
    return True, ("命中关键词：" + "、".join(hits)) if hits else "通过"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run(cases: list[Case], *, verbose: bool = True) -> dict:
    service = ChatService()
    results: list[dict] = []
    started = time.time()

    for index, case in enumerate(cases, start=1):
        truth = truth_value(case)
        stamp = datetime.now().strftime("%H:%M:%S")
        case_started = time.time()
        answer = ""
        error = ""
        try:
            answer = service.ask(None, case.question)["answer"]
        except Exception as exc:                     # noqa: BLE001 —— 任何异常都记下来，评测继续
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - case_started
        ok, hint = judge(case, answer, truth) if not error else (False, error)
        results.append({
            "id": case.id, "category": case.category, "question": case.question,
            "truth": truth if not isinstance(truth, (bytes,)) else str(truth),
            "passed": bool(ok), "detail": hint, "elapsed": round(elapsed, 2),
            "answer_head": (answer or "")[:180].replace("\n", " "),
        })
        if verbose:
            print(f"[{stamp}] {index:>2}/{len(cases)} {case.id:<3} "
                  f"{'PASS' if ok else 'FAIL'} {elapsed:5.1f}s  {case.question[:30]:<32} {hint}")
            if not ok:
                print(f"        回答：{(answer or '')[:200]!r}")
                if truth is not None:
                    print(f"        真值：{truth}")
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_category: dict[str, list[bool]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r["passed"])
    report = {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "seconds": round(time.time() - started, 1),
        "by_category": {k: {"n": len(v), "passed": sum(v),
                            "accuracy": round(sum(v) / len(v), 4)}
                        for k, v in sorted(by_category.items())},
        "failures": [{"id": r["id"], "question": r["question"], "truth": str(r["truth"]),
                      "detail": r["detail"], "answer_head": r["answer_head"]}
                     for r in results if not r["passed"]],
        "results": results,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="项目数据问答准确率评测")
    parser.add_argument("--only", help="只跑某一类，如 sql-finance / knowledge / tool")
    parser.add_argument("--ids", help="只跑指定用例，逗号分隔，如 F1,F2")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--json", dest="json_path", help="把完整报告写成 JSON")
    args = parser.parse_args()

    cases = CASES
    if args.only:
        cases = [c for c in cases if c.category == args.only]
    if args.ids:
        wanted = {s.strip().upper() for s in args.ids.split(",")}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("没有符合条件的用例")
        return 1
    print(f"共 {len(cases)} 条用例，开始评测（真实 Agent + 工具调用）…\n")
    report = run(cases)

    print("\n" + "=" * 72)
    print(f"准确率：{report['passed']}/{report['total']} = {report['accuracy']:.1%}"
          f"（耗时 {report['seconds']}s）")
    print("-" * 72)
    for name, stat in report["by_category"].items():
        print(f"  {name:<14} {stat['passed']}/{stat['n']}  {stat['accuracy']:.1%}")
    if report["failures"]:
        print("-" * 72)
        print("失败用例：")
        for item in report["failures"]:
            print(f"  · {item['id']} {item['question'][:36]}")
            print(f"      真值={item['truth']}｜{item['detail']}")
    print("=" * 72)
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入 {args.json_path}")
    return 0 if report["accuracy"] >= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
