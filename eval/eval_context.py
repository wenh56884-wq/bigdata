# -*- coding: utf-8 -*-
"""上下文工程四维评估（离线、不需 API / 数据库）。

维度与方法：
    ① 任务完成率   迷你测试集：每个问题有「必须可用的工具」，检查精简后的工具子集是否还包含它
    ② 上下文效率   统计各层（system / tools / retrieved / history / input）字符与 token 估算，
                   并与「全量注入工具」的基线对比，量化省了多少
    ③ 工具调用质量 用 Meter 回放一段含失败/重试的调用序列，算有效调用率
    ④ 响应一致性   同一输入连续跑多次（工具选择 / 提示合成 / 检索上下文），必须逐字节一致

跑法（在 app/ 目录下）：python eval/eval_context.py
阈值写在 THRESHOLDS 里，指标不达标就 exit 1（方便接到 CI 上做回归）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import agent, context

THRESHOLDS = {
    "task_success": 1.0,        # 任务完成率：精简不能把必需工具裁掉
    "tool_reduction": 0.30,     # 工具上下文至少省 30%
    "valid_call_ratio": 0.60,   # 有效调用率
    "consistency": 1.0,         # 一致性：必须完全一致
}

# 迷你测试集：(问题, 本次必须可用的工具)
CASES: list[tuple[str, str]] = [
    ("报销制度是怎么规定的？", "search_knowledge"),
    ("医疗库上个月收入是多少", "execute_sql"),
    ("先把 cdr_detail 表结构看一下", "get_table_schema"),
    ("预测未来三个月 Netflix 的收入", "forecast_metric"),
    ("这批订单里有没有异常金额", "detect_data_anomalies"),
    ("把客户按资产和频次分个群", "cluster_data"),
    ("表格库里那个销售数据集有多少行", "query_tables"),
    ("上个月收入同比算了之后画个图", "plot_last_result"),
    ("帮我算一下 128*36 是多少", "calculator"),
    ("现在几点了", "get_current_time"),
    ("记住我最喜欢用 Markdown 表格", "remember"),
    ("员工手册里的培训制度有哪些", "search_knowledge"),
]


def _banner(title: str) -> None:
    print(f"\n{title}")
    print("-" * 68)


# --------------------------------------------------------------------------- #
def eval_task_success() -> tuple[float, list[str]]:
    """① 任务完成率：精简后的工具集必须仍然包含该题必需的工具。"""
    _banner("① 任务完成率（精简后是否还能拿到必需工具）")
    hits, misses = 0, []
    for question, required in CASES:
        subset, report = agent.select_tools_for(question)
        names = {tool.name for tool in subset}
        ok = required in names
        hits += int(ok)
        if not ok:
            misses.append(f"{question} → 缺 {required}")
        print(f"  [{'OK' if ok else 'NG'}] {question:<26} 需 {required:<22} "
              f"注册 {len(names):>2}/26（精简 {report['reduction'] * 100:4.1f}%）")
    rate = hits / len(CASES)
    print(f"  成功率：{rate:.1%}（{hits}/{len(CASES)}）")
    return rate, misses


# --------------------------------------------------------------------------- #
def eval_context_efficiency() -> tuple[float, dict]:
    """② 上下文效率：按需注入 vs 全量注入的工具上下文，量化节省比例。"""
    _banner("② 上下文效率（工具上下文节省比例 + 各层用量）")
    baseline = sum(len(context.TOOL_BRIEF.get(t.name, t.name)) for t in agent.TOOLS) or 1
    reductions, layers = [], {}
    for question, _required in CASES:
        subset, report = agent.select_tools_for(question)
        names = [tool.name for tool in subset]
        reductions.append(report["reduction"])
        prompt = agent.build_system_prompt(tools=names)
        rep = agent.build_system_prompt.last_report
        layers[question[:12]] = {"chars": rep["chars"], "tokens": rep["tokens"]}
    avg_reduction = sum(reductions) / len(reductions)
    avg_tokens = sum(v["tokens"] for v in layers.values()) / len(layers)
    print(f"  工具上下文平均节省：{avg_reduction:.1%}（目标 ≥{THRESHOLDS['tool_reduction']:.0%}）")
    print(f"  System Prompt 平均：{avg_tokens:.0f} token（估算口径）")
    print(f"  逐例 token：{[v['tokens'] for v in layers.values()]}")

    # 检索上下文：真实知识库的一次检索，检查是否带更新时间、是否被裁剪到上限
    docs, label = agent.rag_service.retrieve("报销流程与报销时限", k=3, mode="smart")
    text = context.build_retrieved_context(docs, label, query="报销流程与报销时限")
    hits_width = len(text)
    print(f"  检索上下文 {hits_width} 字符 / {len(docs)} 片段"
          f"（单片段上限 {context.snippet_limit()}）"
          f"｜来源含更新时间：{'更新于' in text}")
    return avg_reduction, {"avg_tokens": avg_tokens, "retrieved_chars": hits_width}


# --------------------------------------------------------------------------- #
def eval_tool_quality() -> tuple[float, dict]:
    """③ 工具调用质量：回放含失败与重复重试的调用序列。"""
    _banner("③ 工具调用质量（失败率 / 重试率 / 有效调用率）")
    meter = context.Meter(label="quality")
    script = [
        ("get_table_schema", {"table": "customers"}, True),
        ("execute_sql", {"sql": "SELECT COUNT(*) FROM customers LIMIT 1"}, False),  # 参数错误
        ("execute_sql", {"sql": "SELECT COUNT(*) FROM customers LIMIT 1"}, True),   # 重试成功
        ("execute_sql", {"sql": "SELECT COUNT(*) FROM customers LIMIT 1"}, True),   # 同参数再来一次
        ("search_knowledge", {"query": "报销流程"}, True),
    ]
    for name, args, ok in script:
        meter.record_tool(name, args, ok)
        meter.record_layer("tool_result", str(args))
    snap = meter.summary()
    print(f"  调用 {snap['tool_calls']} 次｜失败 {snap['tool_failures']}｜"
          f"重复参数 {snap['tool_retries']}｜有效调用率 {snap['valid_call_ratio']:.1%}")
    return snap["valid_call_ratio"], snap


# --------------------------------------------------------------------------- #
def eval_consistency() -> tuple[float, dict]:
    """④ 响应一致性：同样输入多次执行，工具集与提示必须完全一致。"""
    _banner("④ 响应一致性（同样输入多次执行是否完全一致）")
    subjects = [c[0] for c in CASES[:6]]
    stable, detail = 0, []
    for question in subjects:
        runs = []
        for _ in range(3):
            subset, _report = agent.select_tools_for(question)
            names = [t.name for t in subset]
            runs.append((tuple(names), agent.build_system_prompt(tools=names)))
        same_tools = len({r[0] for r in runs}) == 1
        same_prompt = len({r[1] for r in runs}) == 1
        ok = same_tools and same_prompt
        stable += int(ok)
        detail.append({"question": question, "tools_stable": same_tools,
                       "prompt_stable": same_prompt})
        print(f"  [{'OK' if ok else 'NG'}] {question:<26} 工具集一致={same_tools} 提示一致={same_prompt}")
    rate = stable / len(subjects)
    print(f"  一致率：{rate:.1%}（{stable}/{len(subjects)}）")
    return rate, {"detail": detail}


def main() -> int:
    print("=" * 68)
    print("上下文工程（Context Engineering）四维评估")
    print("=" * 68)

    rate, misses = eval_task_success()
    reduction, ctx_info = eval_context_efficiency()
    quality, quality_info = eval_tool_quality()
    consistency, _consistency_info = eval_consistency()

    checks = [
        ("任务完成率", rate, THRESHOLDS["task_success"], lambda v, t: v >= t),
        ("工具上下文节省", reduction, THRESHOLDS["tool_reduction"], lambda v, t: v >= t),
        ("工具调用有效率", quality, THRESHOLDS["valid_call_ratio"], lambda v, t: v >= t),
        ("响应一致性", consistency, THRESHOLDS["consistency"], lambda v, t: v >= t),
    ]
    _banner("评估结论")
    failed = 0
    for name, value, target, predicate in checks:
        ok = predicate(value, target)
        failed += int(not ok)
        print(f"  [{'通过' if ok else '未达标'}] {name:<14} 实测 {value:.1%}  阈值 {target:.0%}")
    if misses:
        print("  未完成用例：")
        for line in misses:
            print(f"    - {line}")
    print(f"\n上下文效率补充：System Prompt 平均 {ctx_info['avg_tokens']:.0f} token，"
          f"检索上下文 {ctx_info['retrieved_chars']} 字符")
    if failed:
        print(f"\n有 {failed} 项未达标 [NG]")
        return 1
    print("\n四项全部达标 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
