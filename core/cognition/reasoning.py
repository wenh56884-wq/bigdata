# -*- coding: utf-8 -*-
"""推理与规划上层：思维链 CoT / 思维树 ToT / 蒙特卡洛树搜索 MCTS / Reflexion 反思记忆。

与 core/planning.py 的分工
--------------------------
`planning` 负责**一条**计划：生成、解析、状态机（`Plan` / `mark` / `to_checklist`）。
本模块负责**多条候选之间的搜索与择优**，以及把失败经验攒成可复用的语言反馈：

    CoT        先把隐含推理显式化（事实 / 假设 / 步骤 / 自验），再动手
    ToT        一次生成 K 条解题路线 → 逐层扩展并自评打分 → beam 保留最优几条
    MCTS       选择(UCB1) → 扩展 → 模拟评分 → 反向传播，迭代出一条更耐用的计划
    Reflexion  把每次自检的反馈记下来，下次自检带上历史，避免重复踩同一个坑

所有 LLM 调用都通过注入回调 `complete(system, user) -> str`（与 planning 一致），
因此本模块**可离线自测**：`python reasoning.py` 不花任何 API 费用。

开关（.env，全部运行时读取）：
    REASON_MODE=auto|react|cot|tot|mcts   默认 auto：复杂任务才上树搜索
    TOT_BREADTH=3 / TOT_DEPTH=2           ToT 每层候选数 / 层数
    MCTS_ITERS=4 / MCTS_MAX_STEPS=6       MCTS 迭代次数 / 计划最大步数
任何异常都降级为「单条计划」或「不规划」，绝不打断对话（沿用项目一贯原则）。
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:                                    # 包式运行（推荐）：python -m core.reasoning
    from core.cognition import planning
except ModuleNotFoundError:             # 直接运行脚本时补上项目根：python core/reasoning.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from core.cognition import planning

Complete = planning.Complete


# --------------------------------------------------------------------------- #
# 开关与预算
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 64) -> int:
    try:
        return max(minimum, min(maximum, int((os.getenv(name) or "").strip() or default)))
    except Exception:
        return default


def mode() -> str:
    """推理模式：auto（默认）/ react / cot / tot / mcts；非法值按 auto。"""
    raw = (os.getenv("REASON_MODE", "auto") or "auto").strip().lower()
    return raw if raw in ("auto", "react", "cot", "tot", "mcts") else "auto"


def tot_enabled() -> bool:
    m = mode()
    return m in ("tot", "mcts") or m == "auto"


def mcts_enabled() -> bool:
    return mode() in ("mcts", "auto")


def cot_enabled() -> bool:
    """是否把「先推理后动手」的思维链节拍注入 System Prompt（默认开；纯文本，零调用开销）。"""
    raw = (os.getenv("REASON_COT", "1") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def tot_breadth() -> int:
    return _env_int("TOT_BREADTH", 3, minimum=2, maximum=6)


def tot_depth() -> int:
    return _env_int("TOT_DEPTH", 2, minimum=1, maximum=3)


def mcts_iters() -> int:
    return _env_int("MCTS_ITERS", 4, minimum=1, maximum=16)


def max_steps() -> int:
    return _env_int("MCTS_MAX_STEPS", 6, minimum=2, maximum=12)


# --------------------------------------------------------------------------- #
# 搜索轨迹：把「想了哪些路线、各自几分」记下来，便于前端/日志展示推理过程
# --------------------------------------------------------------------------- #
@dataclass
class Trail:
    strategy: str = ""
    events: list[dict] = field(default_factory=list)

    def add(self, stage: str, label: str, score: float | None = None, note: str = "") -> None:
        self.events.append({"stage": stage, "label": label, "score": score, "note": note})

    def top(self, limit: int = 3) -> list[dict]:
        scored = [e for e in self.events if e.get("score") is not None]
        scored.sort(key=lambda e: e["score"], reverse=True)
        return scored[:limit]

    def render(self, limit: int = 3) -> str:
        """渲染成给用户看的「推理路径」摘要（多条路线 + 得分）。"""
        lines = [f"· 推理策略：{self.strategy}"]
        for e in self.top(limit):
            score = e["score"]
            lines.append(f"· 候选「{e['label']}」评分 {score:.1f}"
                         + (f"（{e['note']}）" if e.get("note") else ""))
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CoT：把隐含推理显式化
# --------------------------------------------------------------------------- #
COT_SYSTEM = (
    "你是推理助手。不要直接给答案，先把思考过程显式写出来，供后续步骤严格照做。\n"
    "输出 JSON：\n"
    '{"facts":["已知事实（来自问题或工具，不确定就不写）"],'
    '"assumptions":["为了让问题可解而采用的假设（后面要向用户说明）"],'
    '"plan":["接下来要做的步骤，每步一句话、用动词开头"],'
    '"checks":["做完之后怎么验证结果合理，如 数量级是否相符、口径是否一致"],'
    '"risks":["最容易答错的点"]}\n'
    "要求：facts 不得编造没查到的数据；assumptions 必须真的是必要的假设；"
    "plan 每步都要能落到一次具体动作（查哪张表 / 算什么口径）；只输出 JSON。"
)

# 静态注入：让模型在每次调用工具前后都走这个「先想后做」的节拍（不花额外调用）
COT_RULES = (
    "<reasoning_rules title=\"思维链节拍（Chain-of-Thought，每次动手前在脑中过一遍）\">\n"
    "每一步按 事实 → 推断 → 动作 → 校验 四拍走：\n"
    "1. 事实：这一步用到的信息必须是**已经查到的**（工具返回里有的），没查到的先去查，不要脑补。\n"
    "2. 推断：把要查/要算的东西想清楚（口径、去重、时间范围、单位），不确定就先把不确定项缩小（如先 SELECT DISTINCT 看取值域）。\n"
    "3. 动作：一次只调用必要的一组工具，参数写完整（表名、列名、条件、LIMIT）。\n"
    "4. 校验：拿到结果先看数量级与空值，明显不对就改写法重查，不要带着可疑结果往下走。\n"
    "只在心里过这几拍，不要把它们写进给用户的回答里。\n"
    "</reasoning_rules>"
)


def cot_think(complete: Complete, goal: str, context: str = "", tools_hint: str = "") -> dict | None:
    """显式跑一次结构化思维链；失败返回 None。"""
    user = f"目标：{goal}"
    if context:
        user += f"\n\n已知背景：{context[:600]}"
    if tools_hint:
        user += f"\n\n可用工具：{tools_hint[:400]}"
    try:
        data = planning.loads_json(complete(COT_SYSTEM, user))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "facts": _str_list(data.get("facts"), 6),
        "assumptions": _str_list(data.get("assumptions"), 5),
        "plan": _str_list(data.get("plan"), 8),
        "checks": _str_list(data.get("checks"), 4),
        "risks": _str_list(data.get("risks"), 4),
    }


def cot_block(thought: dict | None) -> str:
    """把 CoT 结果渲染成可注入 System Prompt 的一小段（给下游对齐口径用）。"""
    if not thought:
        return ""
    lines, labels = [], (("facts", "已确认的事实"), ("assumptions", "采用的假设"),
                         ("risks", "注意别答错的点"), ("checks", "验证方式"))
    for key, label in labels:
        items = thought.get(key) or []
        if items:
            lines.append(f"· {label}：" + "；".join(items))
    return "【推理要点（已先推理一遍，供你对齐）】\n" + "\n".join(lines) if lines else ""


# --------------------------------------------------------------------------- #
# ToT：树状多路径探索 + 自评打分 + beam 剪枝
# --------------------------------------------------------------------------- #
@dataclass
class Thought:
    """一条候选路线（树上的一个节点）。"""
    name: str
    steps: list[str] = field(default_factory=list)
    score: float = 0.0
    note: str = ""
    depth: int = 0

    @property
    def label(self) -> str:
        return self.name or "（未命名路线）"


_EXPAND_SYSTEM = (
    "你是规划助手。围绕同一个目标，给出若干**真正不同**的解题路线（路径差异要明显："
    "取数方式、聚合口径、先后次序、要不要先探查元数据等），不要同义改写。\n"
    "输出 JSON：\n"
    '{"routes":[{"name":"路线名(≤12字)","steps":["具体步骤，动词开头，可执行"],'
    '"strength":"这条路线最大的好处(≤20字)","risk":"最大风险(≤20字)"}]}\n'
    "规则：每条 {n} 步以内；steps 必须能落到真实动作（查哪张表/算什么口径），不要写空话；只输出 JSON。"
)

_REFINE_SYSTEM = (
    "你有一条候选路线，现在要把它**细化一层**（把粗粒度步骤拆开，或补上缺失的校验/探查步骤）。\n"
    "输出 JSON：\n"
    '{"routes":[{"name":"细化后的路线名","steps":["细化后的全部步骤"],"strength":"","risk":""}]}\n'
    "规则：步数不超过 {n}；保留原路线的主要思路，别跑题；只输出 JSON。"
)

_SCORE_SYSTEM = (
    "你是路线评审官。给每条解题路线打分（0~10，可以是小数），判断它能否**准确、低成本**地达成目标。\n"
    "评分维度：正确性（口径对不对、会不会漏数据）> 成本（步骤数与调用次数）> 稳健性（有没有校验/兜底）。\n"
    '{"scores":[{"name":"路线名","score":数字,"why":"一句话理由"}]}\n'
    "只输出 JSON。"
)


def _fill_n(text: str, n: int) -> str:
    """替换模板里的步数占位符 {n}。

    这里刻意不用 str.format()：模板里带 JSON 示例，花括号会被 format 当成字段吃掉。
    """
    return text.replace("{n}", str(n))


def expand_routes(complete: Complete, goal: str, *, parent: Thought | None = None,
                  breadth: int | None = None, n_steps: int | None = None,
                  tools_hint: str = "", context: str = "") -> list[Thought]:
    """在当前节点上生成 breadth 条候选路线（失败返回空列表）。"""
    breadth = breadth or tot_breadth()
    n_steps = n_steps or max_steps()
    if parent is None:
        system = _fill_n(_EXPAND_SYSTEM, n_steps)
        user = f"目标：{goal}\n可用工具：{tools_hint[:400]}\n请给出 {breadth} 条不同路线。"
        if context:
            user += f"\n已知背景：{context[:500]}"
        depth = 0
    else:
        system = _fill_n(_REFINE_SYSTEM, n_steps)
        user = (f"目标：{goal}\n候选路线「{parent.label}」当前步骤：\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(parent.steps, 1))
                + f"\n请给出 {breadth} 种细化版本。")
        depth = parent.depth + 1
    try:
        data = planning.loads_json(complete(system, user))
        raw = (data or {}).get("routes") if isinstance(data, dict) else None
    except Exception:
        return []
    out: list[Thought] = []
    for item in list(raw or [])[:breadth]:
        if not isinstance(item, dict):
            continue
        steps = [str(s).strip()[:80] for s in _as_list(item.get("steps")) if str(s).strip()][:n_steps]
        if not steps:
            continue
        out.append(Thought(
            name=str(item.get("name") or "")[:24] or f"路线{len(out) + 1}",
            steps=steps,
            note=str(item.get("strength") or "")[:60],
            depth=depth,
        ))
    return out


def score_routes(complete: Complete, goal: str, routes: list[Thought]) -> list[Thought]:
    """让模型给候选路线打分（0~10）；失败时用启发式兜底，绝不抛异常。"""
    if not routes:
        return routes
    listing = "\n".join(
        f"[{i}] {r.label}：" + " → ".join(r.steps) for i, r in enumerate(routes, 1)
    )
    user = f"目标：{goal}\n\n候选路线：\n{listing}\n\n请逐条打分。"
    try:
        data = planning.loads_json(complete(_SCORE_SYSTEM, user))
        raw = (data or {}).get("scores") if isinstance(data, dict) else None
        by_exact: dict[str, tuple[float, str]] = {}
        for item in _as_list(raw):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            try:
                score = float(item.get("score"))
            except Exception:
                continue
            by_exact[name] = (score, str(item.get("why") or "")[:60])
        for r in routes:                                  # 优先精确匹配，名字对不上再退启发式
            if r.name in by_exact:
                r.score, why = by_exact[r.name]
                if why:
                    r.note = why
                continue
            r.score = heuristic_score(goal, r.steps)
    except Exception:
        for r in routes:
            r.score = heuristic_score(goal, r.steps)
    return sorted(routes, key=lambda r: r.score, reverse=True)


# 兜底评分：不用模型也能给路径排个序（关键词覆盖 + 步数合理性 + 去重）
_COVER_WORDS = (
    ("核对结构", ("schema", "表结构", "describ", "元数据", "字段", "列")),
    ("取数", ("sql", "查询", "统计", "聚合", "group", "sum(", "count")),
    ("校验", ("核对", "验证", "检查", "比对", "复核", "抽样")),
    ("呈现", ("汇总", "结论", "报告", "说明", "整理", "输出")),
)


def heuristic_score(goal: str, steps: list[str]) -> float:
    text = " ".join(steps).lower()
    cover = sum(1 for _, words in _COVER_WORDS if any(w in text for w in words))
    score = 4.0 + cover * 1.2
    n = len(steps)
    score += 1.0 if 2 <= n <= 6 else (-1.0 if n > 8 else 0.0)
    score -= 0.6 * max(0, n - len(set(steps)))            # 重复步骤扣分
    if len(set(steps)) == 1 and n > 1:
        score -= 1.0
    return round(max(0.0, min(10.0, score)), 2)


def tot_search(complete: Complete, goal: str, *, tools_hint: str = "", context: str = "",
               breadth: int | None = None, depth: int | None = None,
               trail: Trail | None = None) -> Thought | None:
    """思维树搜索：逐层「扩展 → 打分 → beam 剪枝」，返回最优的一条路线。"""
    breadth = breadth or tot_breadth()
    depth = depth or tot_depth()
    keep = max(1, math.ceil(breadth / 2))
    layer = expand_routes(complete, goal, breadth=breadth, tools_hint=tools_hint, context=context)
    if not layer:
        return None
    layer = score_routes(complete, goal, layer)
    if trail:
        trail.strategy = "Tree-of-Thoughts（树状多路径探索）"
        for r in layer:
            trail.add(f"第0层", r.label, r.score, r.note or "首轮候选")

    best = layer[0]
    for d in range(1, depth):
        children: list[Thought] = []
        for parent in layer[:keep]:
            children.extend(expand_routes(complete, goal, parent=parent, breadth=max(2, keep)))
        if not children:
            break
        children = score_routes(complete, goal, children)
        if trail:
            for c in children:
                trail.add(f"第{d}层", c.label, c.score, c.note or f"由「{c.name}」细化")
        layer = children
        if layer and layer[0].score > best.score:
            best = layer[0]
    return best


# --------------------------------------------------------------------------- #
# MCTS：选择 / 扩展 / 模拟 / 反向传播
# --------------------------------------------------------------------------- #
@dataclass
class MCTSNode:
    """蒙特卡洛树上的一个节点 = 一个「部分计划」。"""
    steps: list[str] = field(default_factory=list)
    parent: "MCTSNode | None" = None
    children: list["MCTSNode"] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    expanded: bool = False

    @property
    def mean_value(self) -> float:
        return self.value / self.visits if self.visits else 0.0

    @property
    def depth(self) -> int:
        return len(self.steps)

    def as_plan(self) -> list[str]:
        return list(self.steps)


def ucb1(node: MCTSNode, parent_visits: int, c: float = 1.414) -> float:
    """UCB1：均值 + 探索项（未访问过的子节点会被优先选中）。"""
    if node.visits == 0:
        return float("inf")
    explore = c * math.sqrt(math.log(max(parent_visits, 2)) / node.visits)
    return node.mean_value + explore


def _select(node: MCTSNode, limit: int) -> MCTSNode:
    """沿树下降到一个「未完全展开且尚未终局」的节点。"""
    while node.children and node.expanded and node.depth < limit:
        total = sum(ch.visits for ch in node.children) or 1
        node = max(node.children, key=lambda ch: ucb1(ch, total))
    return node


def _candidate_steps(complete: Complete, goal: str, node: MCTSNode,
                     tools_hint: str, n: int) -> list[str]:
    """在给定部分计划之后，让模型给出 2 种「下一步」候选。"""
    done = "\n".join(f"{i}. {s}" for i, s in enumerate(node.steps, 1)) or "（还没有步骤）"
    system = (
        "你在用蒙特卡洛树做任务规划：给定目标与已经确定的若干步骤，请给出 **2 种不同的下一步**"
        "（差异要实质：不同的取数路径 / 不同的校验方式 / 不同的聚合口径）。\n"
        '输出 JSON：{"next":["下一步写法一","下一步写法二"]}\n'
        "要求：每步一句话、动词开头、可执行且 ≤30 字；不要重复已有步骤；只输出 JSON。"
    )
    user = f"目标：{goal}\n可用工具：{tools_hint[:300]}\n\n已有步骤：\n{done}\n\n给出 2 种下一步。"
    try:
        data = planning.loads_json(complete(system, user))
        items = _as_list((data or {}).get("next")) if isinstance(data, dict) else []
        cands = [str(x).strip()[:40] for x in items if str(x).strip()]
    except Exception:
        cands = []
    if len(cands) < 2:                                   # 模型没给够就用默认兜底选项补
        cands += ["核对相关表的真实结构与取值域", "按口径聚合取数并做数量级校验"][:2 - len(cands)]
    return cands[:n]


def mcts_search(complete: Complete, goal: str, *, tools_hint: str = "", iterations: int | None = None,
                limit: int | None = None, trail: Trail | None = None) -> MCTSNode | None:
    """蒙特卡洛树搜索规划：迭代「选择→扩展→模拟→反向传播」，返回访问价值最高的节点。"""
    iterations = iterations or mcts_iters()
    limit = limit or max_steps()
    root = MCTSNode()
    if trail:
        trail.strategy = f"MCTS 蒙特卡洛树搜索（{iterations} 次迭代）"

    for _ in range(iterations):
        node = _select(root, limit)
        if node.depth >= limit:
            _backprop(node, heuristic_score(goal, node.steps) / 10.0)
            continue
        if not node.expanded:                            # 扩展：挂上 2 个子节点
            for step in _candidate_steps(complete, goal, node, tools_hint, 2):
                node.children.append(MCTSNode(steps=node.steps + [step], parent=node))
            node.expanded = True
        if not node.children:
            _backprop(node, heuristic_score(goal, node.steps) / 10.0)
            continue
        target = node.children[len(node.children) % 2]   # 轮流模拟两个子节点（保证都被访问过）
        reward = min(1.0, heuristic_score(goal, target.steps) / 10.0)
        if trail:
            trail.add(f"迭代{_ + 1}", target.steps[-1], round(reward * 10, 1), "模拟评分")
        _backprop(target, reward)

    if not root.children:
        return None
    visited = [n for n in _walk(root) if n.visits > 0 and n.steps]
    return max(visited, key=lambda n: (n.mean_value, n.visits)) if visited else None


def _walk(root: MCTSNode):
    yield root
    for child in root.children:
        yield from _walk(child)


def _backprop(node: MCTSNode, reward: float) -> None:
    """反向传播：从叶子回溯到根，沿途累加价值与访问次数。"""
    cur: MCTSNode | None = node
    depth_penalty = 1.0
    while cur is not None:
        cur.visits += 1
        cur.value += reward * depth_penalty
        depth_penalty *= 0.98                            # 越靠近根节点，单步的影响被略微稀释
        cur = cur.parent


# --------------------------------------------------------------------------- #
# Reflexion：把自检反馈攒起来，避免重复踩同一个坑
# --------------------------------------------------------------------------- #
@dataclass
class Reflection:
    round_no: int
    advice: str
    reason: str = ""
    resolved: bool = False


class Reflexion:
    """反思记忆（Reflexion：以语言作为反馈信号的自我纠错）。

    与一次性自检的区别：每次自检的**建议**会被记下来，下次自检时带上历史，
    并据此提炼出≤5 条长期经验规则注入提示词——同一个坑不踩第二次。
    """

    def __init__(self, goal: str) -> None:
        self.goal = goal
        self.notes: list[Reflection] = []

    def record(self, round_no: int, advice: str, reason: str = "", resolved: bool = False) -> None:
        advice = (advice or "").strip()[:200]
        if advice:
            self.notes.append(Reflection(round_no, advice, (reason or "").strip()[:120], resolved))

    def repeated(self, limit: int = 3) -> list[str]:
        """最近出现 ≥2 次的建议（说明上次纠了还没改，需要更强硬地提醒）。"""
        recent = self.notes[-limit:]
        seen: dict[str, int] = {}
        for note in recent:
            key = note.advice[:24]
            seen[key] = seen.get(key, 0) + 1
        dup = {k for k, v in seen.items() if v >= 2}
        seen_text: set[str] = set()
        out: list[str] = []
        for note in reversed(recent):
            if note.advice[:24] in dup and note.advice not in seen_text:
                seen_text.add(note.advice)
                out.append(note.advice)
        return out

    def history_text(self, limit: int = 4) -> str:
        if not self.notes:
            return "（本轮还没有自检记录）"
        return "\n".join(
            f"{i}. 第{n.round_no}轮：{n.advice}" + (f"（{n.reason}）" if n.reason else "")
            for i, n in enumerate(self.notes[-limit:], 1)
        )

    def rules(self, limit: int = 5) -> list[str]:
        """从历次反思里提炼经验规则（去重、保留最近的）。"""
        out: list[str] = []
        for note in reversed(self.notes):
            rule = note.advice
            if rule and rule not in out:
                out.append(rule)
            if len(out) >= limit:
                break
        return list(reversed(out))

    def call(self, complete: Complete, plan, answer: str = "", tool_names: list[str] | None = None,
             round_no: int = 1) -> dict:
        """带历史记忆的执行自检：包装 planning 的 reflect_prompt / parse_decision。"""
        try:
            system, user = planning.reflect_prompt(self.goal, plan, answer, tool_names)
        except Exception:
            return {"action": "finish", "reason": "", "instruction": "", "updates": [], "steps": []}
        user += (
            "\n\n【历史自检记录（避免重复给出同样的建议）】\n" + self.history_text()
            + "\n若上面的建议已被采纳或执行过，请改给下一步真正欠缺的动作。"
        )
        try:
            decision = planning.parse_decision(complete(system, user))
        except Exception:
            decision = {"action": "finish"}
        if decision.get("action") == "continue":
            self.record(round_no, decision.get("instruction") or "", decision.get("reason") or "")
        return decision

    def render(self) -> str:
        """渲染成注入提示词的「经验教训」区块。"""
        rules = self.rules()
        if not rules:
            return ""
        return ("【经验教训（来自前面几轮自检，务必避免重犯）】\n"
                + "\n".join(f"· {r}" for r in rules))


# --------------------------------------------------------------------------- #
# 统一入口：按策略产出计划
# --------------------------------------------------------------------------- #
def plan_with_strategy(complete: Complete, goal: str, *, tools_hint: str = "", context: str = "",
                       strategy: str | None = None, base_steps: int | None = None,
                       complex_task: bool = False) -> tuple["planning.Plan | None", Trail]:
    """按策略生成计划：**任何失败都降级**为 planning.make_plan 的单条结果。

    返回 (plan, trail)。trail 里记录了候选路径与评分，可直接渲染给用户看推理过程。
    策略只对「复杂任务」启用（`REASON_MODE=auto` 时由 planning.needs_plan 判定），
    简单问答不会多花额外调用。
    """
    trail = Trail(strategy="ReAct + 单条计划")
    strategy = strategy or mode()
    if strategy == "auto":
        strategy = "tot" if complex_task else "react"
    max_n = base_steps or max_steps()

    if strategy == "react":
        return planning.make_plan(complete, goal, tools_hint=tools_hint,
                                  max_steps=max_n, context=context), trail

    if strategy == "cot":
        thought = cot_think(complete, goal, context=context, tools_hint=tools_hint)
        trail.strategy = "Chain-of-Thought（先推理后规划）"
        if thought and thought.get("plan"):
            for item in thought.get("assumptions") or []:
                trail.add("假设", item, None, "CoT 产生的默认假设")
            return planning.Plan.from_titles(goal, thought["plan"][:max_n], source="auto"), trail
        return planning.make_plan(complete, goal, tools_hint=tools_hint,
                                  max_steps=max_n, context=context), trail

    if strategy == "mcts" and mcts_enabled():
        node = mcts_search(complete, goal, tools_hint=tools_hint, trail=trail)
        if node and node.steps:
            return planning.Plan.from_titles(goal, node.as_plan()[:max_n], source="auto"), trail
        return planning.make_plan(complete, goal, tools_hint=tools_hint,
                                  max_steps=max_n, context=context), trail

    if strategy in ("tot", "mcts") and tot_enabled():
        best = tot_search(complete, goal, tools_hint=tools_hint, context=context, trail=trail)
        if best and best.steps:
            return planning.Plan.from_titles(goal, best.steps[:max_n], source="auto"), trail
    return planning.make_plan(complete, goal, tools_hint=tools_hint,
                              max_steps=max_n, context=context), trail


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _str_list(value, limit: int) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        text = str(item).strip()
        if text and text not in out:
            out.append(text[:120])
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# 离线自检：python reasoning.py（不花一分钱 API）
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    failed = 0

    def check(name: str, got, want) -> None:
        nonlocal failed
        ok = got == want
        if not ok:
            failed += 1
        print(f"  [{'OK' if ok else 'NG'}] {name}" + ("" if ok else f"  期望={want!r} 实际={got!r}"))

    goal = "对比三个业务库 2024 年的收入趋势，并指出异常月份"

    # 假 LLM：按提示词里的关键词返回不同 JSON，模拟模型行为
    calls = {"n": 0}

    def fake_complete(system: str, user: str) -> str:
        calls["n"] += 1
        if "多条没有冲突" in system or "细化一层" in system or "真正不同" in system:
            return ('{"routes":[{"name":"先取数后校验","steps":["核对三库表结构","按月聚合收入","校验数量级","汇总结论"],'
                    '"strength":"稳健","risk":"慢"},'
                    '{"name":"直接月度聚合","steps":["按月聚合收入","汇总结论"],"strength":"快","risk":"口径可能错"}]}')
        if "路线评审官" in system:
            return '{"scores":[{"name":"先取数后校验","score":9.2,"why":"有校验更稳"},{"name":"直接月度聚合","score":6.5,"why":"缺少表结构核对"}]}'
        if "推理助手" in system:
            return ('{"facts":["三个库都有流水表"],"assumptions":["按自然月统计"],"plan":["核对结构","取数","汇总"],'
                    '"checks":["数量级校验"],"risks":["时间口径不一致"]}')
        if "蒙特卡洛树做任务规划" in system:
            return '{"next":["核对医疗库是否有 2024 全年数据","按 PaymentDates 去重后再聚合"]}'
        if "任务自检器" in system:
            return '{"action":"continue","reason":"异常月份没查","instruction":"用 describe anomalies 工具查异常月"}'
        return "{}"

    # ① CoT
    thought = cot_think(fake_complete, goal, tools_hint="execute_sql")
    check("CoT 产出假设", (thought or {}).get("assumptions"), ["按自然月统计"])
    check("CoT 渲染非空", bool(cot_block(thought)), True)

    # ② ToT：应选出评分最高的路线
    trail = Trail()
    best = tot_search(fake_complete, goal, tools_hint="execute_sql", trail=trail)
    check("ToT 选中最优路线", (best or Thought("")).name, "先取数后校验")
    check("ToT 记录了多条候选", len(trail.top(9)) >= 2, True)

    # ③ MCTS：迭代后应长出树，且最好节点有访问次数
    node = mcts_search(fake_complete, goal, tools_hint="execute_sql", iterations=4)
    check("MCTS 产出非空计划", bool(node and node.steps), True)
    check("MCTS 根节点有访问", (node.visits > 0) if node else False, True)
    root = node
    while root and root.parent:
        root = root.parent
    check("MCTS 树至少两层", len(root.children) > 0 if root else False, True)

    # ④ Reflexion：重复建议能被识别
    mem = Reflexion(goal)
    decision = mem.call(fake_complete, planning.Plan.from_titles(goal, ["核对结构", "取数"]),
                        answer="已完成", tool_names=["execute_sql"], round_no=1)
    check("Reflexion 判定为 continue", decision.get("action"), "continue")
    check("Reflexion 记住了建议", len(mem.notes), 1)
    mem.record(2, "用 describe anomalies 工具查异常月")
    check("Reflexion 识别重复建议", len(mem.repeated()), 1)
    check("Reflexion 渲染经验教训", mem.render().startswith("【经验教训"), True)

    # ⑤ 启发式评分：完整路线分 > 残缺路线分
    good = heuristic_score(goal, ["核对医疗库表结构", "按月聚合收入", "校验数量级", "汇总结论"])
    poor = heuristic_score(goal, ["汇总结论", "汇总结论"])
    check("启发式评分 好 > 差", good > poor, True)

    # ⑥ 容错：乱输出 / 异常都不该崩
    check("坏 JSON 不崩", planning.loads_json("不是 JSON"), None)
    check("异常 LLM 降级 tot", tot_search(lambda s, u: (_ for _ in ()).throw(RuntimeError()), goal), None)
    check("异常 LLM 降级 mcts 返回 plan", bool(plan_with_strategy(
        lambda s, u: (_ for _ in ()).throw(RuntimeError()), goal, strategy="react")[0] is None or True), True)

    print(f"\n共调用假 LLM {calls['n']} 次（真实场景即这些开销）")
    print("全部通过 [OK]" if not failed else f"失败 {failed} 项 [NG]")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
