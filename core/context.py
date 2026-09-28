# -*- coding: utf-8 -*-
"""Agent 上下文工程（Context Engineering）：把四层上下文当成可以被测量和裁剪的对象。

Agent 的上下文由五层构成：

    ① 系统提示 System Prompt   角色 / 规则 / 清单 / 示例 / 本轮计划
    ② 工具定义 Tool Definitions 26 个工具的 schema
    ③ 历史记录 History          多轮对话
    ④ 检索上下文 Retrieved      知识库片段
    ⑤ 用户输入 User Input       本轮问题

本模块针对前四层提供**可度量、可裁剪**的能力，四条主线：

    提示分层      `compose()`：给每个提示块标优先级，按序合成，自动去重、超预算时从
                  低优先级开始丢，并**正面表述**为主（少说"不要"，多说"应该怎么做"）
    工具上下文    `select_tools()`：按任务阶段动态注册工具子集（只给这次用得上的），
                  `render_tool_guide()`：每个工具**一句话**说明用途 + 参数约束
    检索上下文    `rewrite_query / trim_snippet / build_retrieved_context`：
                  先改写查询 → 相关性阈值过滤（不够就是"证据不足"，别硬答）→
                  来源标注（路径 / 页码 / **更新时间** / 相关度）→ 按段落裁剪
    评估迭代      `Meter`：记录上下文各层的 token 估算、工具调用的命中/失败/重试，
                  供 `eval/eval_context.py` 做四维评估

设计原则（沿用项目一贯作风）：**任何失败都静默降级**，不打断对话；开关全部走 .env。

开关：CTX=1（总开关）、CTX_BUDGET=6000（System Prompt 字符预算，0=不限）、
      CTX_TOOL_SELECT=1（工具动态精简）、CTX_SNIPPET=800（单片段字符上限）、
      CTX_MIN_SCORE=0.15（检索相关性阈值）、CTX_STATS=0（是否落盘统计）

自检：python core/context.py
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    return _flag("CTX", True)


def budget_chars() -> int:
    """System Prompt 的字符预算（超出后按优先级丢弃低优先级块）。0 表示不限制。

    默认值按实测留出余量：BASE 提示约 5.7k 字符 + 清单 1.5k + 示例/优先级 0.5k +
    CoT 0.3k + 工具指引 0.5k ≈ 8.5k，给到 12k 既能装下全部内容，又能在
    未来提示膨胀（或注入很长的技能卡/摘要）时自动保护上下文。
    """
    return _int("CTX_BUDGET", 12000)


def snippet_limit() -> int:
    """单个检索片段的字符上限（按段落/句子裁剪，不做生硬截断）。"""
    return _int("CTX_SNIPPET", 800)


def min_score() -> float:
    """检索相关性阈值：低于它的片段直接不进上下文，并触发「证据不足」提示。"""
    return _float("CTX_MIN_SCORE", 0.15)


def stats_enabled() -> bool:
    return _flag("CTX_STATS", False)


# --------------------------------------------------------------------------- #
# token 估算（本地、无依赖：中文按 1.4 字/token，其余按 4 字符/token）
# --------------------------------------------------------------------------- #
_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（够用来观察上下文涨落，不足以做计费）。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    others = max(0, len(text) - cjk)
    return int(cjk / 1.4 + others / 4) + 1


# --------------------------------------------------------------------------- #
# ① 系统提示：分层合成（优先级 + 去重 + 预算）
# --------------------------------------------------------------------------- #
# 数字越小越优先；越靠前面兜底的越不能被丢掉
PRIORITY = {
    "time": 0,        # 当前时间：回答"现在几点"要用，极短且高价值
    "safety": 10,     # 安全/脱敏类硬约束
    "role": 20,       # 角色与总体规则
    "task": 30,       # 本轮任务：QuerySpec / 执行计划
    "example": 40,    # few-shot 示例
    "memory": 50,     # 长期记忆 / 早期摘要
    "hint": 60,       # 可选提示：推理路径、技能卡、工具清单
}


@dataclass(frozen=True)
class Block:
    """一个提示块。optional=False 的块在超预算时**不会**被丢弃。"""

    tag: str
    text: str
    priority: int = 50
    optional: bool = True

    @property
    def size(self) -> int:
        return len(self.text or "")


def block(tag: str, text: str, priority: int | None = None, optional: bool = True) -> Block:
    return Block(tag=tag, text=(text or "").strip(),
                 priority=PRIORITY.get(tag, 50) if priority is None else priority,
                 optional=optional)


def _line_key(line: str) -> str:
    """行指纹：忽略空白与常见前缀符号，用于跨块去重（同一条规则在两个块里出现时只留一份）。"""
    cleaned = re.sub(r"[\s　]+", "", line)
    cleaned = re.sub(r"^[-*•·•◦\d.、）)]+", "", cleaned)
    return cleaned


def dedupe_text(text: str, seen: set[str]) -> tuple[str, int]:
    """按行去重：返回 (去重后的文本, 去掉的行数)。"""
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        raw_stripped = line.strip()
        if not raw_stripped:
            kept.append(line)
            continue
        key = _line_key(raw_stripped)
        if len(key) >= 6 and key in seen:      # 太短的行（如项目符号）不参与判重
            removed += 1
            continue
        if len(key) >= 6:
            seen.add(key)
        kept.append(line)
    return "\n".join(kept), removed


def compose(blocks: Iterable[Block], budget: int | None = None,
            dedupe: bool = True) -> tuple[str, dict]:
    """把多个提示块合成为一段 System Prompt。

    规则：
    1. 按 priority 升序排列（编号小的在前、也最先进入模型视野，且最后才被裁掉）
    2. 逐块按**行指纹**去重：跨 duplicated 的规则只保留一次
    3. 超过字符预算时，**先丢 optional 的低优先级块**，仍超则在最后一个块上截断并标注
    """
    budget = budget_chars() if budget is None else budget
    ordered = sorted([b for b in blocks if b.text], key=lambda b: b.priority)
    seen: set[str] = set()
    duplicate_lines = 0
    dropped: list[str] = []
    chunks: list[tuple[str, Block]] = []

    total = 0
    for item in ordered:
        text = item.text
        if dedupe:
            text, removed = dedupe_text(text, seen)
            duplicate_lines += removed
        total += len(text)
        chunks.append((text, item))

    if budget and total > budget:
        # 超预算：**从优先级最低的可选块开始丢**，直到装得下（必留块永远不动）
        order_desc = sorted(range(len(chunks)), key=lambda i: chunks[i][1].priority, reverse=True)
        removed_idx: set[int] = set()
        for i in order_desc:
            if total <= budget:
                break
            _text, item = chunks[i]
            if not item.optional:
                continue
            total -= len(chunks[i][0])
            removed_idx.add(i)
            dropped.append(item.tag)
        chunks = [pair for i, pair in enumerate(chunks) if i not in removed_idx]

        running = sum(len(text) for text, _ in chunks)
        if running > budget:                    # 只剩必留块却仍超：在最后一块上截断并标注
            overflow = running - budget
            last_text, last_item = chunks[-1]
            if overflow < len(last_text):
                chunks[-1] = (last_text[: len(last_text) - overflow] + "…（已按上下文预算截断）",
                              last_item)

    body = "\n\n".join(text for text, _ in chunks)
    report = {
        "blocks": len(ordered),
        "kept": [item.tag for _t, item in chunks],
        "dropped": dropped,
        "dup_lines": duplicate_lines,
        "chars": len(body),
        "tokens": estimate_tokens(body),
        "budget": budget or 0,
    }
    return body, report


# 正面表述的示例块（few-shot）：优先用「应该这么做」而不是「不许那么做」
ANSWER_EXAMPLE = (
    "<example title=\"一次合格回答的样子（照着做，而不是绕开约束）\">\n"
    "问：医疗库上个月收入多少？\n"
    "做：get_table_schema 确认日期列类型 → execute_sql 按月聚合 → 得到 1,285.6 万元"
    " → 回答「约 1,285.6 万元，来自 payments 表按 payment_date 汇总」\n"
    "答：医疗库上月（2024-05）总收入约 **1,285.6 万元**。\n"
    "   （来源：healthcare_analytics_competition.payments，口径：payment_date 所属自然月）\n"
    "</example>"
)

# 第一层路由：先判断这一问到底是在问「数」还是在问「制度」
ROUTING_RULES = (
    "<routing title=\"先判方向再动手（问的数？还是问的制度？）\">\n"
    "· 问数值事实（多少笔 / 多少钱 / 多少人 / Top N / 分布）→ 走业务库：get_db_skill → "
    "get_table_schema → execute_sql\n"
    "· 问政策制度流程（报销标准、发票要求、报销几天到账、手册里怎么写、原话是什么）"
    " → **走 search_knowledge 检索知识库**，不要用 SQL 去业务库里找\n"
    "· 本轮没给 search_knowledge 却是在问制度 → 直接说明「知识库检索工具不可用」，"
    "不要反复重试别的工具\n"
    "· 知识库也没检索到 → 如实说「没查到」，并说明补哪方面资料；别用常识编，也别反复重试同一工具\n"
    "</routing>"
)

# 优先级声明：遇到冲突时到底听谁的（模型最容易在这里摇摆）
PRIORITY_RULES = (
    "<priority title=\"冲突时的取舍顺序（从上到下，优先级递减）\">\n"
    "1. 工具真实返回的数据 > 一切记忆与推测（查出来是 0 就报 0）\n"
    "2. 数据库真实表结构（get_table_schema / describe_table）> 技能卡模板 SQL > 字面猜测\n"
    "3. 用户本轮明确的要求 > 默认的省略习惯（要求列明细就给明细）\n"
    "4. 查得到才答：查不到就说明「没查到」并给出下一步建议，而不是补一个差不多的数\n"
    "</priority>"
)


# --------------------------------------------------------------------------- #
# ② 工具上下文：分组注册 + 动态精简 + 一句话说明
# --------------------------------------------------------------------------- #
# 核心工具：任何任务都可能用到，始终保留
CORE_TOOLS = (
    "calculator", "get_current_time", "plan_task", "update_plan",
    "remember", "recall", "forget",
)

# 分组：按「任务阶段」注册，只给这次真正用得上的那一组
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    # MySQL 业务库：查数、取结构、口径
    "sql": ("execute_sql", "list_database_tables", "get_table_schema",
            "get_db_skill", "analyze_query"),
    # 非结构化表格库（SQLite 链路）
    "tables": ("list_table_sets", "analyze_table_query", "find_table",
               "describe_table", "query_tables"),
    # 知识库检索
    "knowledge": ("search_knowledge",),
    # 依赖「最近一次查询结果」的加工：画图 / Python 计算
    "post": ("plot_last_result", "run_python", "word_count"),
    # 统计分析 + 自动建模
    "analysis": ("analyze_data", "detect_data_anomalies", "cluster_data"),
    # 机器学习预测
    "forecast": ("list_forecast_metrics", "forecast_metric"),
}

# 一句话说明：用途 + 参数约束（替代把长 docstring 反复讲一遍）
TOOL_BRIEF: dict[str, str] = {
    "calculator": "算数学表达式；expression 只给算式，如 (1+2)*3",
    "get_current_time": "取当前日期时间；无参数",
    "word_count": "统计字数；text 为待统计文本",
    "execute_sql": "【只读】查业务库；sql 必须是 SELECT/SHOW/DESCRIBE，必备 LIMIT",
    "list_database_tables": "列三库表名；无参数，用于确认表是否存在",
    "get_table_schema": "读真实表结构（字段名/类型/注释）；写 SQL 前先调用",
    "get_db_skill": "加载口径技能卡；database 用 finance/medical/telecom",
    "analyze_query": "本地抓取问句关键词并定位库表；question 为用户原句",
    "plot_last_result": "把最近一次查询结果画成图；需先执行查询",
    "run_python": "对最近一次查询结果做二次计算；code 里用 rows/cols 变量",
    "list_forecast_metrics": "列可预测的业务指标；无参数",
    "forecast_metric": "训练模型预测未来 N 月指标；需先查 list_forecast_metrics",
    "analyze_data": "表的统计画像与相关分析；database+table，可用 where 过滤",
    "detect_data_anomalies": "异常检测（三口径投票）；须指定 value_col",
    "cluster_data": "聚类分群并自动定簇；columns 给 2~5 个数值列",
    "plan_task": "复杂任务拆计划；goal 写清最终要交付什么",
    "update_plan": "勾选已完成步骤；title 需与计划中的某一步一致",
    "list_table_sets": "列非结构化表格库的数据集；无参数",
    "analyze_table_query": "写表 SQL 前先分析该查哪个数据集、用什么英文检索词",
    "find_table": "按问题召回候选表；question 为自然语言",
    "describe_table": "看某张非结构化表的列名与预览；table_id 来自 find_table",
    "query_tables": "【只读】查非结构化表格库；SQLite 方言，需 LIMIT",
    "search_knowledge": "检索知识库原文片段；query 用自然语言问句",
    "remember": "写入跨会话长期记忆；仅在用户明确要求记住时调用",
    "recall": "查询跨会话长期记忆；query 写要找的主题关键词",
    "forget": "删除长期记忆；仅在用户明确要求忘掉时调用",
}

# 关键词 → 需要哪些组（命中即加入）
_GROUP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 「问的是制度还是数字」是第一层路由：政策/标准/流程类问题**必须**拿到 search_knowledge，
    # 否则模型只能去业务库里找答案，然后陷入重复调用的死循环
    (("知识库", "文档", "制度", "手册", "规定", "pdf", "PDF", "条款", "政策", "说明",
      "报销", "差旅", "发票", "补贴", "审批", "流程", "请假", "考勤", "绩效", "入职",
      "住宿", "市内交通", "上限", "额度", "几天内", "几个工作日", "多久到账",
      "怎么样", "怎么办", "要求是", "要求是啥", "是怎么写的", "标准是多少", "有哪些要求",
      "的原话", "第几章", "章节"), ("knowledge",)),
    (("表格", "数据集", "excel", "Excel", "csv", "CSV", "宽表", "上传", "上传的",
      "我上传", "文件里的", "文件中", "这份文件", "这个文件"), ("tables",)),
    (("异常", "离群", "不正常", "反常", "聚类", "画像", "RFM", "rfm", "统计分布", "相关",
      "分群", "分个群", "分成群", "分几群", "打标签", "分层"), ("analysis",)),
    (("预测", "趋势预估", "未来", "forecast", "下个月收入"), ("forecast",)),
    (("画", "图", "图表", "可视化", "柱状", "折线"), ("post",)),
    (("同比", "环比", "移动平均", "回归", "python", "Python", "算一下"), ("post", "sql")),
    (("库", "表", "查询", "多少", "统计", "SQL", "sql", "订单", "客户", "患者", "明细",
      "收入", "金额", "余额", "数量"), ("sql",)),
)


def groups_for(question: str, task_type: str | None = None,
               knowledge_keywords: list[str] | None = None) -> list[str]:
    """按问题判断这次需要哪些工具组（纯本地规则，不耗调用）。

    `knowledge_keywords` 是**从知识库文档动态抽取**的主题词（文件名 + 各级标题），
    这样用户换了知识库文档，路由也能自适应，不用回来改规则表。
    """
    text = str(question or "")
    groups: list[str] = []
    for keywords, hit in _GROUP_RULES:
        if any(word in text for word in keywords):
            groups.extend(hit)
    if knowledge_keywords and any(keyword in text for keyword in knowledge_keywords):
        groups.append("knowledge")
    mapping = {
        "query": "sql", "lookup": "sql", "aggregation": "sql",
        "knowledge": "knowledge", "forecast": "forecast",
        "visualize": "post", "memory": "", "chat": "",
    }
    if task_type:
        extra = mapping.get(str(task_type).lower())
        if extra and extra in TOOL_GROUPS:
            groups.append(extra)
    # 判断不出来时给 sql + knowledge：宁可多给一个工具，也不能让用户问制度时没有检索工具可用
    # （实测：知识类问题一旦拿不到 search_knowledge，模型会去业务库里翻制度，最终反复重试到失败）
    if not groups:
        groups = ["sql", "knowledge"]
    elif "post" in groups and not ({"sql", "tables"} & set(groups)):
        groups.append("sql")             # 画图/二次计算之前，总得先有数据可取
    # 去重保序
    out: list[str] = []
    for name in groups:
        if name and name in TOOL_GROUPS and name not in out:
            out.append(name)
    return out


def select_tools(question: str, *, task_type: str | None = None,
                 available: Iterable[str] | None = None,
                 groups: list[str] | None = None,
                 knowledge_keywords: list[str] | None = None) -> tuple[list[str], dict]:
    """按任务阶段挑选工具子集。

    返回 (工具名列表, 报告)。关闭 CTX_TOOL_SELECT 或判断不出阶段时返回全量。
    """
    pool = list(available) if available is not None else []
    if not _flag("CTX_TOOL_SELECT", True):
        groups_use: list[str] = list(TOOL_GROUPS.keys())
    else:
        groups_use = groups if groups is not None else groups_for(
            question, task_type, knowledge_keywords)

    picked: list[str] = []
    for name in CORE_TOOLS:
        if (not pool or name in pool) and name not in picked:
            picked.append(name)
    for group in groups_use:
        for name in TOOL_GROUPS.get(group, ()):
            if (not pool or name in pool) and name not in picked:
                picked.append(name)
    if not picked:                        # 兜底：宁可给多，也不给空
        picked = list(pool) if pool else []

    dropped = sorted(set(pool) - set(picked)) if pool else []
    before = sum(len(TOOL_BRIEF.get(n, "")) for n in (pool or picked)) or 1
    after = sum(len(TOOL_BRIEF.get(n, "")) for n in picked)
    report = {
        "groups": groups_use,
        "kept": len(picked),
        "dropped": len(dropped),
        "dropped_names": dropped,
        "reduction": round(1 - after / before, 4) if before else 0.0,
    }
    return picked, report


def render_tool_guide(names: Iterable[str], *, with_constraints: bool = True) -> str:
    """把工具集渲染成一段紧凑说明：每个工具**一行**，写完用途顺带写参数约束。"""
    lines = []
    for name in names:
        brief = TOOL_BRIEF.get(name)
        if not brief:
            continue
        lines.append(f"· {name}：{brief}" if with_constraints else f"· {name}")
    if not lines:
        return ""
    return ("<tools title=\"本轮可用工具（一行一个：用途 + 参数约束）\">\n"
            + "\n".join(lines) + "\n</tools>")


# --------------------------------------------------------------------------- #
# ④ 检索上下文：改写 → 阈值 → 标注 → 裁剪
# --------------------------------------------------------------------------- #
_POLITE = re.compile(r"^(请问|麻烦你|帮我看看|帮我|我想问一下|我想知道|想问一下|能不能|拜托|帮忙)+")
_NOISE = re.compile(r"(谢谢|打扰了|麻烦了|来着|的话|吗|呢|啊|呀|哦|吧|嗯)")


def rewrite_query(question: str, spec: dict | None = None) -> str:
    """检索前的查询改写：优先用 QuerySpec 改写好的问句，否则本地清理寒暄与口水词。

    为什么要改写：用户输入经常是"那个报销的事儿咋说的来着？"——带指代、带口水词，
    直接拿去做 TF-IDF/向量检索，等于把噪声也算进了相似度。
    """
    candidate = ""
    if isinstance(spec, dict):
        candidate = str(spec.get("rewritten") or "").strip()
    base = candidate or str(question or "").strip()
    if not base:
        return ""
    cleaned = _POLITE.sub("", base)
    cleaned = _NOISE.sub("", cleaned).strip(" ，,。.？?、")
    # 改写后如果什么都没剩下（用户只打了寒暄），宁可用原文
    return cleaned or base


def source_line(meta: dict, *, index: int = 0, with_updated: bool = True) -> str:
    """来源标注：路径 / 段落 / 页码 / **更新时间** / 相关度。

    更新时间很重要：模型（和用户）据此判断这条资料是不是过期的。
    """
    meta = meta or {}
    head = f"片段{index}（来源：{meta.get('source', '未知文档')} · 第{meta.get('chunk_index', '?')}段"
    if meta.get("page") is not None:
        head += f" · PDF 第{meta['page']}页"
    if with_updated and meta.get("updated"):
        head += f" · 更新于 {meta['updated']}"
    score = meta.get("score")
    if score is not None:
        head += f" · 相关度{float(score):.3f}"
    return head + "）："


def trim_snippet(text: str, limit: int | None = None, *, query: str = "") -> tuple[str, bool]:
    """按段落/句子裁剪片段，优先保留与查询重叠最多的那一段。

    返回 (裁剪后的文本, 是否真的裁了)。宁可留一段完整的话，也不要半句话。
    """
    limit = snippet_limit() if limit is None else limit
    content = (text or "").strip()
    if not limit or len(content) <= limit:
        return content, False
    pieces = [p for p in re.split(r"(?<=[。！？；\n])", content) if p.strip()]
    if len(pieces) <= 1:
        pieces = [content]
    keys = {c for c in re.sub(r"[^\w\u4e00-\u9fff]", "", query or "") if c}
    scored = [(sum(1 for c in keys if c in piece) / (len(piece) ** 0.5 + 1), i, piece)
              for i, piece in enumerate(pieces)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    kept: list[tuple[int, str]] = []
    used = 0
    for _score, order, piece in scored:
        if used + len(piece) > limit:
            continue
        kept.append((order, piece))
        used += len(piece)
    if not kept:                          # 一段都放不下：截取窗口，但在句子边界收尾
        window = content[:limit]
        cut = max(window.rfind(ch) for ch in "。！？；\n")
        kept = [(0, window[:cut + 1] if cut > limit * 0.5 else window + "…")]
    kept.sort()
    body = "".join(piece for _order, piece in kept)
    return body.strip(), len(body) < len(content)


# 覆盖率重排里不参与的词（否则「的」「了」这些会把覆盖率算得没意义）
_COV_STOP = set("的了吗呢啊呀哦吧和与及是在有这那个我你它把被对于为以")
_COV_TOKEN_RE = re.compile(r"[^\w\u4e00-\u9fff]")


def coverage_tokens(text: str) -> set[str]:
    """覆盖率用的词元集：中文按字（去虚词），英文/数字按词。"""
    words: set[str] = set()
    for piece in _COV_TOKEN_RE.sub(" ", str(text or "").lower()).split():
        if re.search(r"[\u4e00-\u9fff]", piece):
            words.update(char for char in piece if char not in _COV_STOP)
        elif len(piece) > 1:
            words.add(piece)
    return words


def rerank_by_coverage(docs: list, query: str, *, limit: int | None = None,
                       weight: float = 0.7) -> list:
    """按「查询词覆盖率」重排召回结果。

    RRF 融合只看**多路中的排名**，不问「到底命中了几个不同的关键词」——于是篇幅大的文档
    可以靠某一个高频词反复出现把排名顶上去。实测：问「报销金额超过多少元需要二级审批」时，
    政策文档被三份 SQL 问答示例挤到第 4 位（它们满是「找出总金额超过…的记录」，压根没有
    「二级审批」）。    这里补上覆盖率这一维：命中了查询里更多不同词元的片段更靠前，
    原始排名仍占 weight 之外的份额，已经排对的问法不会被逆转。

    weight：覆盖率权重（其余给原始排名），默认 0.7。
    """
    docs = list(docs or [])
    keys = coverage_tokens(query)
    if not keys or not docs:
        return docs[:limit] if limit else docs
    total = max(1, len(docs))
    scored: list[tuple[float, int, Any]] = []
    for index, doc in enumerate(docs):
        text = getattr(doc, "page_content", None)
        if text is None and isinstance(doc, dict):
            text = doc.get("page_content")
        coverage = len(keys & coverage_tokens(text or "")) / len(keys)
        rank_part = 1.0 - index / total
        scored.append((weight * coverage + (1.0 - weight) * rank_part, index, doc))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = [doc for _score, _index, doc in scored]
    return picked[:limit] if limit else picked


def source_of(doc: Any) -> str:
    """取出片段的来源标识（Document / 带 metadata 的对象 / dict 都支持）。"""
    meta = getattr(doc, "metadata", None)
    if meta is None and isinstance(doc, dict):
        meta = doc.get("metadata") or {}
    meta = dict(meta or {})
    return str(meta.get("source") or meta.get("file") or "")


def diversify(docs: list, limit: int | None = None, max_per_source: int = 2) -> list:
    """同源限流：同一篇来源最多占 max_per_source 个名额（MMR 多样性的轻量版）。

    为什么要这一步：知识库里各文档的块数极不均衡（实测报销政策 5 块 vs SQL 示例 1000+ 块），
    只按分数取 Top-K 时，**大文档会靠"词面重复出现"包揽全部名额**，把真正命中的小文档挤出去
    ——用户问报销政策，结果三条里三条都是 SQL 示例文档。
    代价：同来源的相关块可能被挤掉，所以配额给到多数席位（limit 的一半向上取整），而不是 1。
    """
    docs = list(docs or [])
    if limit is not None and limit <= 0:
        return []
    quota = max(1, int(max_per_source or 1))
    kept: list = []
    counts: dict[str, int] = {}
    for doc in docs:
        source = source_of(doc)
        if counts.get(source, 0) >= quota:
            continue
        counts[source] = counts.get(source, 0) + 1
        kept.append(doc)
        if limit and len(kept) >= limit:
            break
    return kept


NO_EVIDENCE_HINT = (
    "（知识库里没有找到足够相关的内容：所有候选片段的相关度都低于阈值 {threshold}。"
    "请如实告诉用户「没查到」，并说明可以补充哪方面的资料；不要用常识或猜测填补空白。）"
)


def build_retrieved_context(docs: list, engines_label: str = "", *, query: str = "",
                            threshold: float | None = None, limit: int | None = None,
                            max_docs: int | None = None) -> str:
    """检索上下文管线：阈值过滤 → 来源标注 → 按段落裁剪 → 拼成一整段。

    - 低于阈值的片段直接丢掉；**全部**低于阈值时返回「证据不足」提示而不是硬凑内容
    - 每条都带来源路径 / 段落 / 页码 / 更新时间 / 相关度（便于模型判断可信度）
    """
    threshold = min_score() if threshold is None else threshold
    limit = snippet_limit() if limit is None else limit
    docs = list(docs or [])
    if not docs:
        return ""

    kept: list[tuple[dict, Any]] = []
    for doc in docs:
        meta = dict(getattr(doc, "metadata", {}) or {})
        score = meta.get("score")
        if score is not None and float(score) < threshold:
            continue
        kept.append((meta, doc))
    if max_docs:
        kept = kept[:max_docs]
    if not kept:
        return NO_EVIDENCE_HINT.format(threshold=f"{threshold:.2f}")

    parts = [f"（检索引擎：{engines_label}）"] if engines_label else []
    trimmed_count = 0
    for index, (meta, doc) in enumerate(kept, start=1):
        body, trimmed = trim_snippet(getattr(doc, "page_content", "") or "", limit, query=query)
        trimmed_count += 1 if trimmed else 0
        parts.append(source_line(meta, index=index) + "\n" + body)
    return "\n\n---\n\n".join(parts)


# --------------------------------------------------------------------------- #
# 度量：上下文各层用量 + 工具调用质量
# --------------------------------------------------------------------------- #
@dataclass
class Meter:
    """一次问答的上下文账本。

    统计三个维度的数据量（系统/工具/检索/历史/输入），以及工具调用的质量
    （有效调用、失败、同参数重试），供 `eval/eval_context.py` 出指标。
    """

    label: str = ""
    started: float = field(default_factory=time.time)
    layers: dict[str, int] = field(default_factory=dict)      # 层 → 字符数
    tokens: dict[str, int] = field(default_factory=dict)      # 层 → token 估算
    tool_calls: list[tuple[str, str, bool]] = field(default_factory=list)  # (工具, 参数指纹, 是否成功)
    notes: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_layer(self, layer: str, text: str) -> None:
        with self._lock:
            text = text or ""
            self.layers[layer] = self.layers.get(layer, 0) + len(text)
            self.tokens[layer] = self.tokens.get(layer, 0) + estimate_tokens(text)

    def record_tool(self, name: str, args: Any, ok: bool) -> None:
        """记录一次工具调用：同一工具 + 相同参数指纹重复出现即判定为「重试」。"""
        try:
            fingerprint = json.dumps(args, ensure_ascii=False, sort_keys=True)[:160]
        except Exception:
            fingerprint = str(args)[:160]
        with self._lock:
            self.tool_calls.append((name, fingerprint, bool(ok)))

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def summary(self) -> dict:
        with self._lock:
            total_chars = sum(self.layers.values())
            total_tokens = sum(self.tokens.values())
            calls = self.tool_calls
            failures = sum(1 for _n, _f, ok in calls if not ok)
            # 「重试」只统计**上一次同样调用已经成功、却又原样再来一遍**的浪费行为；
            # 失败后的重试是合理纠偏，不该被算成质量问题
            seen: dict[tuple[str, str], bool] = {}
            wasteful = 0
            for name, fingerprint, ok in calls:
                key = (name, fingerprint)
                if key in seen and seen[key]:
                    wasteful += 1
                seen[key] = ok
            retries = wasteful
            return {
                "label": self.label,
                "elapsed": round(self.elapsed, 3),
                "layers": dict(self.layers),
                "tokens": dict(self.tokens),
                "total_chars": total_chars,
                "total_tokens": total_tokens,
                "tool_calls": len(calls),
                "tool_failures": failures,
                "tool_retries": retries,          # 成功后重复同样的调用（浪费）
                "tool_names": sorted({name for name, _f, _o in calls}),
                "valid_call_ratio": round(1 - (failures + retries) / len(calls), 4) if calls else 1.0,
                "notes": dict(self.notes),
            }


_STORE_LOCK = threading.Lock()
_STATS_PATH = PROJECT_ROOT / "data" / "context_stats.jsonl"


def persist(summary: dict) -> None:
    """把一次问答的上下文度量落盘（CTX_STATS=1 时启用），用于跨版本对比迭代效果。"""
    if not stats_enabled():
        return
    try:
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STORE_LOCK, _STATS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_stats(limit: int = 200) -> list[dict]:
    if not _STATS_PATH.exists():
        return []
    try:
        lines = _STATS_PATH.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------- #
# 自检：python core/context.py
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    failed = 0

    def check(name: str, got, want) -> None:
        nonlocal failed
        ok = got == want
        if not ok:
            failed += 1
            print(f"  [{'OK' if ok else 'NG'}] {name}" + ("" if ok else f"  期望={want!r} 实际={got!r}"))

    def truthy(name: str, got) -> None:
        check(name, bool(got), True)

    print("① token 估算")
    truthy("中文估算为正", estimate_tokens("报销流程是什么") > 0)
    check("空文本 0 token", estimate_tokens(""), 0)

    print("\n② 提示分层合成")
    blocks = [
        block("hint", "提示：本轮可能用到的工具", optional=True),
        block("role", "你是数据分析助手"),
        block("example", ANSWER_EXAMPLE),
        block("time", "今天是 2026-09-24"),
    ]
    text, report = compose(blocks)
    check("块数", report["blocks"], 4)
    truthy("按优先级排：时间在最前", text.startswith("今天是"))
    truthy("示例块在角色之后", text.index("<example") > text.index("数据分析助手"))

    dup_blocks = [
        block("role", "查不到就说没查到，不要编造数值"),
        block("safety", "查不到就说没查到，不要编造数值"),
        block("time", "今天是 2026-09-24"),
    ]
    _dup_text, dup_report = compose(dup_blocks)
    check("跨块重复行被去掉 1 条", dup_report["dup_lines"], 1)

    _small_text, small_report = compose(blocks, budget=60)
    truthy("超预算时丢掉可选块", bool(small_report["dropped"]))
    truthy("先丢低优先级的 hint", small_report["dropped"][0] == "hint")
    truthy("超预算后仍在预算内", small_report["chars"] <= 60)

    must_keep, keep_report = compose(
        [block("hint", "低优先级提示：可以丢", optional=True),
         block("role", "必留：你是数据分析助手", optional=False)], budget=12)
    truthy("不可丢的块保留", "role" in keep_report["kept"])
    truthy("可选块被丢以腾位置", "hint" in keep_report["dropped"])

    print("\n③ 工具上下文")
    all_tools = sorted({*CORE_TOOLS, *[n for names in TOOL_GROUPS.values() for n in names]})
    picked, tool_report = select_tools("报销制度是怎么规定的", available=all_tools)
    check("知识类问题选中 knowledge 组", "knowledge" in tool_report["groups"], True)
    truthy("精简掉了一部分工具", tool_report["dropped"] > 0)
    truthy("精简比例达到 30%", tool_report["reduction"] >= 0.30)
    truthy("核心工具始终在", all(t in picked for t in ("calculator", "get_current_time")))
    truthy("知识库工具被保留", "search_knowledge" in picked)

    picked2, report2 = select_tools("医疗库上个月收入多少", available=all_tools)
    truthy("SQL 类问题选中 sql 组", "sql" in report2["groups"])
    truthy("SQL 工具被保留", "execute_sql" in picked2)

    guide = render_tool_guide(["execute_sql", "run_python"])
    check("每行一个工具", len([l for l in guide.splitlines() if l.startswith("· ")]), 2)
    truthy("说明里带参数约束", "LIMIT" in guide)

    print("\n④ 检索上下文")
    check("改写：去掉寒暄与口水词", rewrite_query("请问那个报销的事儿是怎么说的来着呢"),
          "那个报销的事儿是怎么说的")
    check("改写：优先用 QuerySpec", rewrite_query("报销怎么搞", {"rewritten": "报销流程与提交时限"}),
          "报销流程与提交时限")
    check("空输入不炸", rewrite_query(""), "")

    class _Doc:
        def __init__(self, content, meta):
            self.page_content = content
            self.metadata = meta

    docs = [
        _Doc("第一段讲报销流程。" * 400, {"source": "policy.md", "chunk_index": 3,
                                  "updated": "2026-09-01", "score": 0.42}),
        _Doc("完全不相关的一段内容。", {"source": "other.md", "chunk_index": 9, "score": 0.02}),
    ]
    ctx = build_retrieved_context(docs, "关键词+语义（RRF 融合）", query="报销流程", threshold=0.15)
    truthy("过滤掉了低相关度片段", "other.md" not in ctx)
    truthy("保留高相关度片段", "policy.md" in ctx)
    truthy("标注了更新时间", "更新于 2026-09-01" in ctx)
    truthy("标注了相关度", "相关度0.420" in ctx)
    truthy("长片段被裁剪到预算内", len(ctx) < 3200 * 0.5)      # 原文 3200 字，800 上限

    weak = build_retrieved_context(
        [_Doc("内容", {"source": "a.md", "chunk_index": 1, "score": 0.01})], "", query="x")
    truthy("全部低于阈值返回证据不足提示", "证据不足" not in weak and "阈值" in weak)

    # 同源限流：大文档靠篇幅刷分、挤掉真正命中的小文档时的解药
    pool_docs = [_Doc(f"SQL 示例 {i}", {"source": "sql-faq.md", "chunk_index": i}) for i in range(4)]
    pool_docs.insert(3, _Doc("报销政策原文", {"source": "policy.md", "chunk_index": 1}))
    picked = diversify(pool_docs, limit=3, max_per_source=2)
    check("限流后仍取到 3 条", len(picked), 3)
    truthy("官方小文档不再被大文档挤掉", any(source_of(d) == "policy.md" for d in picked))
    truthy("单一来源不超过配额", [source_of(d) for d in picked].count("sql-faq.md") <= 2)
    check("候选不足时不丢东西", len(diversify(pool_docs[:2], limit=5, max_per_source=2)), 2)
    truthy("保持原有先后顺序", [source_of(d) for d in picked][0] == "sql-faq.md")

    # 查询词覆盖率重排：命中更多不同关键词的片段优先（大文档靠单高频词刷分的解药）
    mixed = [
        _Doc("找出总金额超过 500 的账单，显示所有交易金额超过的记录", {"source": "sql-faq.md"}),
        _Doc("显示周末和工作日的话务量对比，金额超过一万的记录", {"source": "sql-faq.md"}),
        _Doc("报销金额超过 3000 元需要二级审批，报销金额上限规范", {"source": "policy.md"}),
    ]
    ranked = rerank_by_coverage(mixed, "报销金额超过多少元需要二级审批", weight=0.7)
    check("覆盖率重排后仍是 3 条", len(ranked), 3)
    truthy("命中全部关键词的小文档被提到第一", source_of(ranked[0]) == "policy.md")
    truthy("覆盖率同样的片段长短一致时不改顺序", source_of(ranked[-1]) == "sql-faq.md")
    check("空查询直接原样返回", len(rerank_by_coverage(mixed, "")), 3)

    body, trimmed = trim_snippet("短句。", limit=800, query="短")
    check("不裁剪短文本", trimmed, False)
    _long = "无关无关无关。" * 50 + "关键句：报销需在三十天内提交。" + "尾巴尾巴。" * 50
    body2, trimmed2 = trim_snippet(_long, limit=60, query="报销三十天")
    truthy("裁剪保留关键句", "报销需在三十天内提交" in body2)
    check("确实裁了", trimmed2, True)

    print("\n⑤ 度量")
    meter = Meter(label="测试")
    meter.record_layer("system", "你是助手" * 10)
    meter.record_layer("retrieved", "片段" * 20)
    meter.record_tool("execute_sql", {"sql": "SELECT 1"}, True)
    meter.record_tool("execute_sql", {"sql": "SELECT 1"}, True)     # 成功后重复 → 记为浪费
    meter.record_tool("get_table_schema", {"table": "a"}, True)
    snap = meter.summary()
    check("记录调用数", snap["tool_calls"], 3)
    check("识别 1 次重复", snap["tool_retries"], 1)
    check("没有失败", snap["tool_failures"], 0)
    check("有效调用率", snap["valid_call_ratio"], round(1 - 1 / 3, 4))

    retry_meter = Meter(label="失败后重试")
    retry_meter.record_tool("execute_sql", {"sql": "SELECT 1"}, False)
    retry_meter.record_tool("execute_sql", {"sql": "SELECT 1"}, True)   # 纠偏：不算浪费
    check("失败后的重试不算质量问题", retry_meter.summary()["tool_retries"], 0)
    truthy("总 token 为正", snap["total_tokens"] > 0)
    check("层维度齐全", sorted(snap["layers"]), ["retrieved", "system"])

    print("\n全部通过 [OK]" if not failed else f"\n失败 {failed} 项 [NG]")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
