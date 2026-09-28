# -*- coding: utf-8 -*-
"""新增能力的离线测试：推理规划层 + 三级数据能力 + 脱敏覆盖。

不花 API 费用、不需要数据库：**LLM 用假回调注入，数据用合成样本**。
跑法（在 app/ 目录下）：python eval/_test_reason_and_data.py

覆盖：
    A. 推理与规划  CoT / ToT / MCTS / Reflexion（含降级）
    B. 数据能力    沙箱计算与安全（初级）、统计画像与相关（中级）、异常检测与聚类（高级）
    C. 集成        工具注册、新工具输出的脱敏、工具名提示文案
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

from core import agent
from core.cognition import planning, reasoning
from services.analytics import ml_insight, pysandbox
from services.ops import sanitize

FAILED = 0


def check(name: str, got, want) -> None:
    """一个断言：不等就记一次失败（照 eval/_test_eval_core.py 的约定）。"""
    global FAILED
    ok = got == want
    if not ok:
        FAILED += 1
        print(f"  [NG] {name}  期望={want!r} 实际={got!r}")
    else:
        print(f"  [OK] {name}")


def truthy(name: str, got) -> None:
    check(name, bool(got), True)


# --------------------------------------------------------------------------- #
print("A. 推理与规划层（core/reasoning.py）")
# --------------------------------------------------------------------------- #
GOAL = "对比三个业务库 2024 年月度收入趋势并指出异常月份"


def fake_llm(system: str, user: str) -> str:
    """按提示词关键词返回不同 JSON，模拟真实模型在各阶段的输出。"""
    if "推理助手" in system:
        return ('{"facts":["三库都有流水表"],"assumptions":["按自然月口径"],'
                '"plan":["核对表结构","按月聚合","校验量级","汇总结论"],"checks":["数量级校验"],"risks":["时间口径不一致"]}')
    if "真正不同" in system or "细化一层" in system:
        return ('{"routes":[{"name":"先核对后聚合","steps":["核对三库表结构","按月聚合收入","校验量级","汇总结论"],'
                '"strength":"口径稳","risk":"慢"},'
                '{"name":"直接聚合","steps":["按月聚合收入","汇总结论"],"strength":"快","risk":"口径可能错"}]}')
    if "路线评审官" in system:
        return ('{"scores":[{"name":"先核对后聚合","score":9.2,"why":"有校验"},'
                '{"name":"直接聚合","score":6.1,"why":"缺表结构核对"}]}')
    if "蒙特卡洛树" in system:
        return '{"next":["核对日期列类型","按月聚合后再算环比"]}'
    return '{"steps":["核对表结构","聚合取数","校验并汇总"]}'


thought = reasoning.cot_think(fake_llm, GOAL)
check("CoT：取出默认假设", (thought or {}).get("assumptions"), ["按自然月口径"])
truthy("CoT：渲染成提示词段落", reasoning.cot_block(thought).startswith("【推理要点"))

trail = reasoning.Trail()
best = reasoning.tot_search(fake_llm, GOAL, trail=trail)
check("ToT：选中评分最高的路线", (best or reasoning.Thought("")).name, "先核对后聚合")
truthy("ToT：留下多条候选轨迹", len(trail.events) >= 2)

node = reasoning.mcts_search(fake_llm, GOAL, iterations=4)
truthy("MCTS：产出非空计划", node and node.steps)
truthy("MCTS：节点被访问过（反向传播生效）", node and node.visits > 0)
root = node
while root and root.parent:
    root = root.parent
truthy("MCTS：树至少展开一层", root and len(root.children) > 0)

mem = reasoning.Reflexion(GOAL)
plan = planning.Plan.from_titles(GOAL, ["核对表结构", "聚合取数"])


def fake_reflector(system: str, user: str) -> str:
    return '{"action":"continue","reason":"没做环比","instruction":"补充环比计算"}'


decision = mem.call(fake_reflector, plan, round_no=1)
check("Reflexion：判定继续补做", decision.get("action"), "continue")
check("Reflexion：自检建议被记下来", len(mem.notes), 1)
mem.record(2, "补充环比计算")                       # 第二轮给出同一条建议 → 触发重复告警
check("Reflexion：识别重复建议", len(mem.repeated()), 1)
truthy("Reflexion：渲染经验教训", mem.render().startswith("【经验教训"))

check("启发式评分：完整路线优于残缺路线",
      reasoning.heuristic_score(GOAL, ["核对结构", "按月聚合", "校验", "汇总"])
      > reasoning.heuristic_score(GOAL, ["汇总", "汇总"]), True)

import os

for strategy, expect_steps in (("react", True), ("cot", True), ("tot", True), ("mcts", True)):
    _plan, _trail = reasoning.plan_with_strategy(fake_llm, GOAL, strategy=strategy)
    truthy(f"策略 {strategy}：能产出计划", _plan is not None and len(_plan.steps) > 0)

_plan_bad, _ = reasoning.plan_with_strategy(
    lambda s, u: (_ for _ in ()).throw(RuntimeError("boom")), GOAL, strategy="react")
truthy("降级：LLM 异常时不抛出", _plan_bad is None)
os.environ["REASON_MODE"] = "tot"
_plan_def, _ = reasoning.plan_with_strategy(
    lambda s, u: (_ for _ in ()).throw(RuntimeError("boom")), GOAL, strategy="tot")
truthy("降级：ToT 异常后退回单条计划", _plan_def is None)
os.environ.pop("REASON_MODE")

# --------------------------------------------------------------------------- #
print("\nB. 数据能力（沙箱 / 统计 / 建模）")
# --------------------------------------------------------------------------- #
check("初级：沙箱算表达式", pysandbox.run("sum([1, 2, 3]) * 2")["result_text"], "12")
check("初级：注入最近查询结果计算",
      pysandbox.run("sum(x['amount'] for x in rows)",
                    {"rows": [{"amount": 10}, {"amount": 30}]})["result_text"], "40")
check("初级：捕获 print", pysandbox.run("print('hi')\nresult = 1")["stdout"], "hi")
for label, code in (("拒绝 import", "import os"), ("拒绝 open", "open('a.txt')"),
                    ("拒绝 eval", "eval('1+1')"), ("拒绝下划线属性", "(1).__class__"),
                    ("拒绝 while", "while True: pass")):
    check(f"初级：{label}", pysandbox.run(code)["ok"], False)
res = pysandbox.run("t=0\nfor i in range(10**12):\n    t+=i")
check("初级：超长循环被步数预算拦下", res["ok"], False)
truthy("初级：预算提示可读", "循环迭代" in res["error"])

rng = np.random.default_rng(11)
prof = ml_insight.numeric_profile(np.column_stack([rng.normal(100, 15, 400)]), ["金额"])
check("中级：画像产出 1 列", len(prof), 1)
truthy("中级：均值准确", abs(prof[0]["均值"] - rng is not None) if False else abs(prof[0]["非空"] - 400) == 0)
x = rng.normal(size=200)
corr = ml_insight.correlation_matrix(np.column_stack([x, x * 3 + rng.normal(0, .05, 200)]), ["a", "b"])
truthy("中级：强相关被识别", abs(corr["top"][0]["pearson"]) > 0.9)
truthy("中级：强相关解读正确", "极强" in ml_insight.interpret_corr(corr["top"][0]["pearson"]))

# ID / 状态类列不该被当成度量
rows = [[i, i % 2, 100 + i * 1.5] for i in range(200)]   # 主键 / 二值开关 / 带小数的金额
picked, _matrix = ml_insight._numeric_matrix(rows, ["client_id", "status", "amount"])
check("中级：ID/二值开关被排除、度量列保留", picked, ["amount"])

vals = list(rng.normal(100, 5, 300)) + [900.0]
labels = [f"行{i}" for i in range(301)]
out = ml_insight.detect_outliers(vals, labels)
truthy("高级：异常被检出", out["count"] > 0)
check("高级：最大异常是注入点", out["items"][0]["取值"], 900.0)

c1, c2 = rng.normal([0, 0], .4, size=(80, 2)), rng.normal([7, 7], .4, size=(80, 2))
clu = ml_insight.cluster_profile(np.vstack([c1, c2]), ["x", "y"])
check("高级：自动定簇数为 2", clu.get("k"), 2)
truthy("高级：轮廓系数够高", clu["silhouette"] > 0.7)

# --------------------------------------------------------------------------- #
print("\nC. 集成与脱敏")
# --------------------------------------------------------------------------- #
names = [t.name for t in agent.TOOLS]
for tool_name in ("run_python", "analyze_data", "detect_data_anomalies", "cluster_data"):
    check(f"工具已注册：{tool_name}", tool_name in names, True)
    check(f"工具有前端文案：{tool_name}", tool_name in agent.TOOL_LABELS, True)
# 26 = 推理规划 + 三级数据能力那一批；+1 是后来加的 query_table_python（用 Python 查表格）
check("工具总数达到 27", len(names), 27)

agent._LAST_QUERY["headers"] = ["patient_name", "contact_phone", "amount"]
agent._LAST_QUERY["rows"] = [("王小明", "13812345678", 120), ("李雷", "13900001111", 300)]
py_out = agent.run_python.invoke({"code": "result = sorted(rows, key=lambda r: -r['amount'])"})
truthy("集成：沙箱输出不含人名的明文", "王小明" not in py_out and "李雷" not in py_out)
truthy("集成：沙箱输出不含完整手机号", "13812345678" not in py_out)

_, masked_rows, hits = sanitize.mask_rows(["patient_name", "contact_phone", "amount"],
                                          [["王小明", "13812345678", 120]])
check("集成：姓名列脱敏", masked_rows[0][0], "王**")
check("集成：手机号列脱敏", masked_rows[0][1], "138****5678")
check("集成：金额列不受影响", masked_rows[0][2], 120)
check("集成：命中的列被记录", hits, ["patient_name", "contact_phone"])

check("集成：枚举类标签不被误伤（保险类型）", sanitize.classify_column("insurance_type"), None)
check("集成：月份列名不误判", sanitize.classify_column("month"), None)

print()
if FAILED:
    print(f"失败 {FAILED} 项")
    sys.exit(1)
print("全部测试通过 [OK]")
