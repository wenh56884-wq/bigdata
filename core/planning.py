"""规划引擎（Planning）—— 让 Agent 具备「先规划、再执行、后反思」的能力。

职责边界
--------
本模块只做三件与模型无关的事，**自己不调用任何 LLM**：

1. **提示词构造**：把「目标 + 可用工具 + 上下文」渲染成规划 / 反思 / 拆解用的 system+user 文本；
2. **输出解析**：把模型返回的内容（容忍代码围栏、前后解释、数组/对象混写）解析成结构化计划；
3. **状态机**：Plan / PlanStep 维护步骤状态（待办 / 进行中 / 已完成 / 已跳过 / 失败）与进度。

模型调用通过 complete(system, user) -> str 回调注入（agent.py 传的是 _llm_complete），
好处有两层：① 同一套规划能力可被聊天主链路、深度搜索、命令行复用；
② 解析与状态机可以离线单测（python planning.py），不花一分钱 API 费用。

与既有功能的关系（合并，而不是并存）
------------------------------------
- 深度搜索原本自带一套「拆子问题」「查漏补缺」的 JSON 提示词与解析
  （agent._deep_plan_queries / agent._gap_fill_queries），这里统一为
  research_queries() / gap_queries()，agent.py 里只留薄封装，不再重复实现；
- agent._extract_string_list 的容错解析逻辑合并进 parse_string_list()，
  agent.py 直接代理调用，避免两套「从文本里抠 JSON 数组」的代码。

Agent = LLM(大脑) + Planning(规划) + Tool use(执行) + Memory(记忆)
本模块负责其中的 **Planning**：把「大脑」的一次性回答，升级为「先拆解 → 按步执行 → 自检闭环」。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

# 模型调用回调：(system, user) -> 纯文本
Complete = Callable[[str, str], str]

# ------------------------------ 步骤状态 ------------------------------ #
PENDING = "pending"      # 待办
DOING = "doing"          # 进行中
DONE = "done"            # 已完成
SKIPPED = "skipped"      # 已跳过
FAILED = "failed"        # 失败

STATUSES = (PENDING, DOING, DONE, SKIPPED, FAILED)
STATUS_LABEL = {
    PENDING: "待办",
    DOING: "进行中",
    DONE: "已完成",
    SKIPPED: "已跳过",
    FAILED: "失败",
}
STATUS_MARK = {
    PENDING: "[ ]",
    DOING: "[~]",
    DONE: "[x]",
    SKIPPED: "[-]",
    FAILED: "[!]",
}
# 中文 / 英文 / 符号都容忍
_STATUS_ALIASES = {
    "pending": PENDING, "todo": PENDING, "waiting": PENDING, "待办": PENDING,
    "未开始": PENDING, "未完成": PENDING,
    "doing": DOING, "in_progress": DOING, "running": DOING, "进行中": DOING,
    "处理中": DOING, "开始": DOING,
    "done": DONE, "ok": DONE, "success": DONE, "已完成": DONE, "完成": DONE, "好了": DONE,
    "skipped": SKIPPED, "skip": SKIPPED, "已跳过": SKIPPED, "跳过": SKIPPED, "无需": SKIPPED,
    "failed": FAILED, "fail": FAILED, "error": FAILED, "失败": FAILED, "出错": FAILED,
}


def normalize_status(value: Any, default: str = PENDING) -> str:
    """把模型/用户给的状态词（中英文、大小写）归一成内部状态。"""
    text = str(value or "").strip().lower()
    return _STATUS_ALIASES.get(text, default)


@dataclass
class PlanStep:
    """计划中的一步：一个可执行、可验证的动作。"""

    id: int
    title: str
    status: str = PENDING
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "status_label": STATUS_LABEL.get(self.status, self.status),
            "note": self.note,
        }


@dataclass
class Plan:
    """一份任务计划：目标 + 有序步骤 + 进度，供 Agent 边执行边勾选。"""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    source: str = "auto"      # auto（系统自动规划）/ manual（模型调用 plan_task）/ restored（会话元数据恢复）

    # -- 构造 / 序列化 ---------------------------------------------------- #
    @classmethod
    def from_titles(cls, goal: str, titles: Iterable[str], source: str = "auto") -> "Plan":
        now = _now()
        steps = [
            PlanStep(id=i, title=str(t).strip())
            for i, t in enumerate(titles, start=1)
            if str(t).strip()
        ]
        return cls(goal=goal, steps=steps, created_at=now, updated_at=now, source=source)

    @classmethod
    def from_dict(cls, data: dict) -> "Plan | None":
        """从落盘的会话元数据恢复计划（损坏时返回 None，不影响对话）。"""
        if not isinstance(data, dict) or not data.get("goal"):
            return None
        steps: list[PlanStep] = []
        for index, raw in enumerate(data.get("steps") or [], start=1):
            if isinstance(raw, dict):
                steps.append(
                    PlanStep(
                        id=int(raw.get("id") or index),
                        title=str(raw.get("title") or "").strip(),
                        status=normalize_status(raw.get("status"), PENDING),
                        note=str(raw.get("note") or ""),
                    )
                )
            elif str(raw).strip():
                steps.append(PlanStep(id=index, title=str(raw).strip()))
        steps = [s for s in steps if s.title]
        if not steps:
            return None
        return cls(
            goal=str(data.get("goal") or ""),
            steps=steps,
            revision=int(data.get("revision") or 1),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            source=str(data.get("source") or "restored"),
        )

    def to_dict(self) -> dict:
        done, total = self.progress()
        return {
            "goal": self.goal,
            "revision": self.revision,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [step.to_dict() for step in self.steps],
            "progress": {"done": done, "total": total},
        }

    # -- 状态机 ------------------------------------------------------------ #
    def pending(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status in (PENDING, DOING)]

    def progress(self) -> tuple[int, int]:
        done = sum(1 for s in self.steps if s.status in (DONE, SKIPPED))
        return done, len(self.steps)

    def finished(self) -> bool:
        """所有步骤都已终结（完成 / 跳过 / 失败）即为跑完；失败也算终结，避免死循环。"""
        return bool(self.steps) and all(s.status in (DONE, SKIPPED, FAILED) for s in self.steps)

    def mark(self, ref: Any, status: Any = DONE, note: str = "") -> "PlanStep | None":
        """按「序号（1 起）/ 标题关键字 / 步骤 id」定位并更新状态，命中返回该步骤。"""
        step = self.find(ref)
        if step is None:
            return None
        step.status = normalize_status(status, DONE)
        if note:
            step.note = str(note).strip()[:200]
        self.updated_at = _now()
        return step

    def find(self, ref: Any) -> "PlanStep | None":
        text = str(ref or "").strip()
        if not text:
            return None
        number = re.search(r"\d+", text)
        if number:
            index = int(number.group(0))
            for step in self.steps:
                if step.id == index:
                    return step
        lower = text.lower()
        for step in self.steps:                      # 先精确匹配标题
            if step.title.lower() == lower:
                return step
        for step in self.steps:                      # 再退化为包含匹配
            if lower and (lower in step.title.lower() or step.title.lower() in lower):
                return step
        return None

    def add_steps(self, titles: Iterable[str]) -> list["PlanStep"]:
        """反思/重规划时追加新步骤（自动续编 id），返回新增的步骤。"""
        added: list[PlanStep] = []
        next_id = max((s.id for s in self.steps), default=0) + 1
        for title in titles:
            title = " ".join(str(title).split())[:60]
            if not title or any(title == s.title for s in self.steps):
                continue
            step = PlanStep(id=next_id, title=title)
            self.steps.append(step)
            added.append(step)
            next_id += 1
        if added:
            self.revision += 1
            self.updated_at = _now()
        return added

    # -- 给模型看的文本 ---------------------------------------------------- #
    def to_checklist(self) -> str:
        lines = []
        for step in self.steps:
            line = f"{step.id}. {STATUS_MARK.get(step.status, '[ ]')} {step.title}"
            if step.note:
                line += f"（{step.note}）"
            if step.status == DOING:
                line += " ← 当前应推进这一步"
            lines.append(line)
        return "\n".join(lines)

    def summary(self) -> str:
        done, total = self.progress()
        return f"目标：{self.goal}（进度 {done}/{total}）\n{self.to_checklist()}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 文本 → 结构化：容错解析（模型有时会加代码围栏 / 前后解释 / 写成对象）
# --------------------------------------------------------------------------- #
def strip_code_fence(text: str) -> str:
    """去掉三反引号代码围栏。"""
    return re.sub(r"^[\x60]{3}[a-zA-Z]*\s*|\s*[\x60]{3}$", "", (text or "").strip(), flags=re.S)


def loads_json(text: str) -> Any | None:
    """从模型输出里抠出并解析 JSON（数组或对象）；失败返回 None。"""
    if not text:
        return None
    cleaned = strip_code_fence(text)
    candidates = [cleaned]
    # 截取第一个 [ 或 { 到最后一个 ] 或 } 之间的片段（容忍前后有解释文字）
    start = min((i for i in (cleaned.find("["), cleaned.find("{")) if i >= 0), default=-1)
    end = max(cleaned.rfind("]"), cleaned.rfind("}"))
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return None


def parse_string_list(text: str, limit: int | None = None) -> list[str]:
    """容错解析「字符串数组」：优先 JSON，失败则按行兜底。

    合并自 agent._extract_string_list（深度搜索拆解 / 查漏补缺都走这里）。
    """
    if not text:
        return []
    cleaned = strip_code_fence(text)
    data = loads_json(cleaned)
    if isinstance(data, list):
        items = [str(x).strip() for x in data if str(x).strip()]
        if items:
            return items[:limit] if limit else items
    if isinstance(data, dict):
        # 有的模型会返回 {"queries": [...]} / {"1": "…", "2": "…"}
        for key in ("queries", "steps", "items", "list", "questions"):
            if isinstance(data.get(key), list):
                items = [str(x).strip() for x in data[key] if str(x).strip()]
                if items:
                    return items[:limit] if limit else items
        items = [str(v).strip() for v in data.values() if str(v).strip()]
        if items:
            return items[:limit] if limit else items
    # 兜底：一行一条（去序号 / 项目符号 / 引号）
    items = []
    for line in re.split(r"[\n;；]+", cleaned):
        line = re.sub(r"^[\s\-*•\d.)\[\]\"']+|[\"']+\s*$", "", line).strip()
        if not line or line.startswith("{"):
            continue
        if line.endswith(("：", ":")):   # 引导语（如“计划如下：”）不是步骤
            continue
        items.append(line)
    return items[:limit] if limit else items


def _title_of(item: Any) -> str:
    """数组元素既可能是「标题字符串」，也可能是 {"title": "…"} / {"step": "…"}。"""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("title", "step", "task", "name", "action", "desc", "description", "content"):
            if item.get(key):
                return str(item[key]).strip()
        values = [str(v).strip() for v in item.values() if isinstance(v, (str, int, float))]
        return values[0] if values else ""
    if item is None:
        return ""
    return str(item).strip()


def parse_plan(text: str, goal: str, max_steps: int = 6, source: str = "auto") -> "Plan | None":
    """把模型的规划输出解析成 Plan；解析不出来返回 None（调用方降级为「不规划」）。"""
    data = loads_json(text)
    titles: list[str] = []
    plan_goal = goal
    if isinstance(data, list):
        titles = [_title_of(x) for x in data]
    elif isinstance(data, dict):
        for key in ("steps", "plan", "tasks", "todo", "todos", "items"):
            if isinstance(data.get(key), list):
                titles = [_title_of(x) for x in data[key]]
                break
        else:
            titles = [_title_of(v) for k, v in data.items() if not isinstance(v, (list, dict))]
        if data.get("goal"):
            plan_goal = str(data["goal"]).strip() or goal
    else:
        # 完全没有 JSON：按行兜底，但要求至少 2 条，避免把模型的“一句废话”当成计划
        fallback = parse_string_list(text, limit=max_steps)
        titles = fallback if len(fallback) >= 2 else []
    # 去空、去重、按上限截断
    seen: set[str] = set()
    cleaned: list[str] = []
    for title in titles:
        title = " ".join(str(title).split())[:60]
        if title and title not in seen:
            seen.add(title)
            cleaned.append(title)
    if not cleaned:
        return None
    plan = Plan.from_titles(plan_goal, cleaned[:max_steps], source=source)
    return plan if plan.steps else None


def parse_decision(text: str) -> dict:
    """解析反思输出：{"action","reason","instruction","updates","steps"}，缺失字段给安全默认值。"""
    data = loads_json(text)
    result: dict = {"action": "finish", "reason": "", "instruction": "", "updates": [], "steps": []}
    if isinstance(data, dict):
        action = str(data.get("action") or data.get("decision") or "").strip().lower()
        if action in ("continue", "replan", "redo", "again", "继续", "重规划"):
            result["action"] = "replan" if action in ("replan", "重规划") else "continue"
        elif action in ("finish", "done", "stop", "complete", "完成", "结束"):
            result["action"] = "finish"
        elif data.get("instruction"):
            result["action"] = "continue"
        result["reason"] = str(data.get("reason") or data.get("why") or "").strip()[:200]
        result["instruction"] = str(data.get("instruction") or data.get("next") or "").strip()[:300]
        for raw in data.get("updates") or data.get("steps") or []:
            if isinstance(raw, dict):
                result["updates"].append(
                    {
                        "step": raw.get("step") or raw.get("id") or raw.get("title") or raw.get("index"),
                        "status": normalize_status(raw.get("status"), DONE),
                        "note": str(raw.get("note") or "")[:200],
                    }
                )
        for raw in data.get("new_steps") or data.get("add_steps") or []:
            title = _title_of(raw)
            if title:
                result["steps"].append(title[:60])
    elif isinstance(data, list):
        # 模型直接给了新步骤列表 → 视为重规划
        result["action"] = "replan"
        result["steps"] = [_title_of(x)[:60] for x in data if _title_of(x)][:4]
    return result


# --------------------------------------------------------------------------- #
# 提示词构造（返回 (system, user)）
# --------------------------------------------------------------------------- #
def plan_prompt(goal: str, tools_hint: str = "", max_steps: int = 6, context: str = "") -> tuple[str, str]:
    """任务规划提示词：把目标拆成可执行步骤（要求模型只回 JSON）。"""
    system = (
        "你是任务规划器（Planner），负责把用户目标拆解成 Agent 可以一步步执行的计划。\n"
        "要求：\n"
        f"1. 拆成 2~{max_steps} 步，每步是「一个明确动作 + 明确产出」，彼此不重叠、可验证；\n"
        "2. 每步不超过 30 个字，用动词开头（如「查询医疗库 8 月收入」「按科室汇总并排名」）；\n"
        "3. 步骤要能落到 Agent 的真实能力上，不要写「思考一下」「仔细分析」这类空话；\n"
        "4. 如果目标本身足够简单（一句话就能回答），也允许只给 1 步；\n"
        '5. 只输出一个 JSON 对象：{"goal": "一句话目标", "steps": ["步骤一", "步骤二"]}\n'
        "6. 不要输出 JSON 以外的任何解释文字，不要加代码块标记。"
    )
    if tools_hint:
        system += f"\n（Agent 当前可用工具：{tools_hint}）"
    user = f"用户目标：{goal}"
    if context:
        user += f"\n\n补充上下文：\n{context}"
    return system, user


def reflect_prompt(goal: str, plan: "Plan", answer: str = "",
                   tool_names: list[str] | None = None) -> tuple[str, str]:
    """执行自检提示词：判断计划是否真的完成，未完成则给出下一步指令。"""
    system = (
        "你是任务自检器（Reflector）。给你一个正在执行的计划、Agent 已经调用的工具、"
        "以及它准备给出的回答，请判断「计划是否已经真正完成、回答是否覆盖了目标」。\n"
        "输出一个 JSON 对象：\n"
        '{"action": "finish" 或 "continue", "reason": "一句话理由", '
        '"instruction": "若 continue：下一步具体该做什么（≤60字）", '
        '"updates": [{"step": 序号, "status": "done/doing/skipped/failed", "note": "说明"}], '
        '"new_steps": ["确实需要新增的步骤标题"]}\n'
        "规则：\n"
        "- action=finish 表示无需再执行，可以直接把回答交给用户；\n"
        "- action=continue 表示还存在未完成的关键步骤，必须给出 instruction；\n"
        "- updates 用来修正步骤的真实状态（不要谎报已完成）；\n"
        "- 不要为「锦上添花」的信息要求 continue，只针对目标里明确要求的内容；\n"
        "- 只输出 JSON，不要任何其它文字。"
    )
    user = (
        f"目标：{goal}\n\n当前计划：\n{plan.to_checklist()}\n\n"
        f"本轮已调用的工具：{'、'.join(tool_names) if tool_names else '（无）'}\n\n"
        f"Agent 准备给出的回答（可能被截断）：\n{(answer or '（空）')[:1200]}"
    )
    return system, user


def research_queries_prompt(question: str, max_queries: int = 4) -> tuple[str, str]:
    """深度搜索的子问题拆解提示词（合并自 agent._deep_plan_queries）。"""
    system = (
        "你负责把用户的问题拆解成适合在「本地知识库（产品手册 / FAQ / 政策文档等）」中检索资料的"
        "多个子查询，以便分别检索后再综合成一份完整回答。\n"
        "要求：\n"
        f"1. 拆成 2~{max_queries} 个彼此不重叠、覆盖不同侧面的子问题；\n"
        "2. 每个子查询要具体、聚焦、是独立的检索词，避免一句问多个话题；\n"
        '3. 只输出一个 JSON 字符串数组，例如 ["子查询一", "子查询二"]；\n'
        "4. 不要输出 JSON 之外的任何解释文字、不要代码块标记。"
    )
    return system, f"问题：{question}"


def gap_queries_prompt(question: str, snippets: list[str]) -> tuple[str, str]:
    """查漏补缺提示词（合并自 agent._gap_fill_queries）。"""
    system = (
        "你在帮一个深度检索流程做「查漏补缺」。下面是已经检索到的知识库片段摘要。\n"
        "判断：仅凭这些资料，能否完整、准确地回答用户的问题？\n"
        "- 如果已经足够或问题在这些资料范围内有答案，输出 []；\n"
        "- 如果明显缺关键信息（某个方面完全没覆盖），输出 1~2 个最能补齐缺口的新检索子查询。\n"
        "只输出一个 JSON 字符串数组，不要其它文字。"
    )
    shown = [f"[{i}] {line}" for i, line in enumerate(snippets[:12], start=1)]
    user = f"用户问题：{question}\n\n已有片段摘要：\n" + ("\n".join(shown) or "（无）")
    return system, user


# --------------------------------------------------------------------------- #
# 高层封装：注入 complete 即可拿到结构化结果（agent.py 用的就是这几个）
# --------------------------------------------------------------------------- #
def make_plan(complete: Complete, goal: str, tools_hint: str = "", max_steps: int = 6,
              context: str = "", source: str = "auto") -> "Plan | None":
    """让模型为目标产出计划；任何异常/解析失败都返回 None（调用方降级为不规划）。"""
    try:
        system, user = plan_prompt(goal, tools_hint=tools_hint, max_steps=max_steps, context=context)
        return parse_plan(complete(system, user), goal, max_steps=max_steps, source=source)
    except Exception:
        return None


def research_queries(complete: Complete, question: str, max_queries: int = 4) -> list[str]:
    """深度搜索：把问题拆成若干子查询（去重 + 限长 + 限量）。"""
    try:
        system, user = research_queries_prompt(question, max_queries=max_queries)
        raw = complete(system, user)
    except Exception:
        return []
    out, seen = [], set()
    for query in parse_string_list(raw):
        query = " ".join((query or "").split())
        if query and query not in seen and len(query) <= 200:
            seen.add(query)
            out.append(query)
    return out[: max(max_queries, 2)]


def gap_queries(complete: Complete, question: str, snippets: list[str]) -> list[str]:
    """深度搜索：根据已有片段判断缺口，返回 1~2 个补充子查询（足够时返回 []）。"""
    try:
        system, user = gap_queries_prompt(question, snippets)
        raw = complete(system, user)
    except Exception:
        return []
    return [q for q in parse_string_list(raw) if "[]" not in q][:2]


def reflect(complete: Complete, goal: str, plan: "Plan", answer: str = "",
            tool_names: list[str] | None = None) -> dict:
    """执行自检：返回 {"action","reason","instruction","updates","steps"}；失败默认 finish。"""
    try:
        system, user = reflect_prompt(goal, plan, answer=answer, tool_names=tool_names)
        return parse_decision(complete(system, user))
    except Exception:
        return {"action": "finish", "reason": "自检调用失败，按已完成处理",
                "instruction": "", "updates": [], "steps": []}


# --------------------------------------------------------------------------- #
# 启发式：这个问题值不值得先规划（省钱：简单问题不额外调模型）
# --------------------------------------------------------------------------- #
_SEQ_CUES = (
    "然后", "接着", "再", "最后", "其次", "之后", "依次", "分别", "逐个", "逐一",
    "步骤", "流程", "先", "第一步", "一步步", "逐步",
)
_ANALYSIS_CUES = (
    "对比", "比较", "汇总", "整合", "综合", "分析", "评估", "预测", "报告",
    "方案", "规划", "总结", "排序", "排名", "趋势", "占比", "环比", "同比",
)
_SCOPE_CUES = (
    "所有", "全部", "每个", "各个", "三个库", "多个", "同时", "并且", "以及",
    "还要", "顺便", "一起",
)


def needs_plan(question: str) -> tuple[bool, str]:
    """判断问题是否需要先做计划（返回 (是否需要, 命中的理由)）。

    打分规则（够 3 分才规划）：多步骤动作 2 分 + 分析/对比类目标 2 分 +
    多对象/多范围 1 分 + 多问句 1 分 + 长问题 1 分。简单问题（如「1+1 等于几」）得 0 分，
    因此不会为它多花一次模型调用。
    """
    text = (question or "").strip()
    if not text:
        return False, ""
    score = 0
    reasons: list[str] = []
    hits_seq = [c for c in _SEQ_CUES if c in text]
    hits_analysis = [c for c in _ANALYSIS_CUES if c in text]
    hits_scope = [c for c in _SCOPE_CUES if c in text]
    if hits_seq:
        # 出现 2 个以上顺序词（先…然后…最后）基本可以断定是多步骤指令
        score += 2 + min(len(hits_seq) - 1, 1)
        reasons.append("含多步骤动作：" + "、".join(hits_seq[:3]))
    if hits_analysis:
        # 命中的分析类目标越多，越像“需要组织多个查询/多步加工”的任务
        score += 2 + min(len(hits_analysis) - 1, 2)
        reasons.append("含分析/对比类目标：" + "、".join(hits_analysis[:3]))
    if hits_scope:
        score += 1
        reasons.append("涉及多个对象：" + "、".join(hits_scope[:3]))
    if len(re.findall(r"[？?；;]", text)) >= 2 or len(re.findall(r"[。！!]", text)) >= 2:
        score += 1
        reasons.append("包含多个问句/分句")
    if len(text) >= 60:
        score += 1
        reasons.append("问题较长")
    return score >= 3, "；".join(reasons)


# --------------------------------------------------------------------------- #
# 离线自检：python planning.py（不调用任何模型，零成本）
# --------------------------------------------------------------------------- #
def _selftest() -> None:
    print("【启发式判定：这个问题值不值得先规划】")
    for question in (
        "帮我算一下 123*456",
        "现在几点了？",
        "上个月医疗库总收入是多少？",
        "先查医疗库 8 月收入，然后和 7 月对比，最后给出结论",
        "预测三个库未来三个月趋势并生成报告，顺便画个图",
        "按科室统计收入占比，并对比去年同期的同比变化，整合成一份分析",
    ):
        need, reason = needs_plan(question)
        print(f"  {'需规划' if need else '免规划'}  {question}   ← {reason or '无明显多步特征'}")

    print("\n【计划解析（容错：围栏 / 前后解释 / 对象 / 一行一条）】")
    fence = chr(96) * 3
    samples = [
        f'{fence}json\n{{"goal": "对比三库收入", "steps": ["查医疗库收入", "查金融库收入", "汇总对比"]}}\n{fence}',
        '好的，计划如下：\n["拆分子问题", "逐条检索", "综合回答"]',
        '[{"title": "读取表结构", "status": "done"}, {"title": "编写 SQL"}, "执行并回复"]',
        '{"1": "取数", "2": "建模", "3": "出报告"}',
        "这不是 JSON，但可以一行一条：\n1. 取数\n2. 建模\n- 出报告",
        "模型彻底跑偏，完全没法解析",
    ]
    for sample in samples:
        plan = parse_plan(sample, "测试目标", max_steps=6)
        print(f"  → {plan.summary() if plan else '解析失败（降级为不规划，不影响对话）'}\n")

    print("【状态机：勾选 / 定位 / 追加 / 进度】")
    plan = Plan.from_titles("对比三库收入", ["查医疗库收入", "查金融库收入", "汇总对比"])
    plan.mark(1, "done", "已取到 12 个月数据")
    plan.mark("金融", DOING)
    print(plan.summary())
    done, total = plan.progress()
    print(f"  进度 {done}/{total}，是否跑完：{plan.finished()}")
    print("  追加步骤：", [s.title for s in plan.add_steps(["补充同比数据"])])
    plan.mark(2, "done")
    plan.mark(3, "done")
    plan.mark(4, "skipped")
    print(f"  全部勾选后是否跑完：{plan.finished()}")

    print("\n【反思解析】")
    print(" ", parse_decision(
        '{"action":"continue","reason":"第二个库还没查","instruction":"查询金融库收入",'
        '"updates":[{"step":1,"status":"done"}],"new_steps":["补充同比"]}'))
    print(" ", parse_decision("[]"))
    print(" ", parse_decision("模型抽风了，没给 JSON"))
    print(" ", parse_decision('{"action":"finish","reason":"目标已达成"}'))


if __name__ == "__main__":
    _selftest()
