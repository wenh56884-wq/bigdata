# -*- coding: utf-8 -*-
"""提示词工程：把「口头一问」翻译成「模型能精确执行的查询意图」（Query Understanding）。

为什么需要这一层
----------------
NL→SQL 的错大多不是 SQL 语法错，是**没听懂**：

  * 「上个月营收怎么样」——自然月还是最近 30 天？含不含退款？
  * 「哪款套餐最好」——"好"是按价格、销量还是投诉率排？
  * 「那它的趋势呢」——"它"指上一轮查的那张表还是那个客户？

这些歧义如果丢给同一个 ReAct 循环去猜，模型会在反复试工具的过程中慢慢消歧，
代价是多轮无效调用、口径还可能漂移。本模块把消歧**提前**到一次便宜的结构化调用
（温度 0、短输出），产出一份 QuerySpec 注入当轮提示词：

    改写后的完整问题 → 时间范围的**具体日期** → 聚合口径 → 排序 / TopN
    → 显式列出歧义 → 对应的默认假设 → SQL 写法提示

后面取数时不容易跑偏，回答里也能把口径说清楚，而不是默默按自己的假设给个数。
这就是提示词工程里收益最大的一步：**把隐含信息显式化**。

另外两块常量（`SQL_GUARDRAILS` / `ANSWER_DISCIPLINE`）是把散在各处的经验规则收敛成
一份「写 SQL 前必查」与「回答前必查」的清单，以独立区块注入 System Prompt——
清单式的约束比夹在长段落里的约束遵循率高得多。

开关（.env）：`QUND=1` 默认开（只对像「问数据」的问题触发，闲聊 / 纯算术不浪费调用）；
`QUND=0` 关闭，回到原行为。

自检：python prompting.py
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

# --------------------------------------------------------------------------- #
# 开关
# --------------------------------------------------------------------------- #
def enabled() -> bool:
    raw = (os.getenv("QUND") or "").strip().lower()
    if not raw:
        return True
    return raw in ("1", "true", "yes", "on")


KIND_LABELS = {
    "lookup": "明细查询",
    "aggregate": "汇总统计",
    "rank": "排名 / TopN",
    "trend": "趋势 / 时间序列",
    "compare": "对比 / 同比环比",
    "forecast": "预测",
    "rag": "文档问答",
    "calc": "纯计算",
    "chat": "闲聊 / 闲谈",
    "other": "其它",
}

DB_LABELS = {
    "financial_asset_management": "金融业务库",
    "healthcare_analytics_competition": "医疗业务库",
    "telecom_operations_db": "通信业务库",
    "tables": "非结构化表格库",
    "knowledge": "知识库",
    "": "暂不需要 / 不定",
}


# --------------------------------------------------------------------------- #
# 是否值得跑一次理解（省调用、省延迟）
# --------------------------------------------------------------------------- #
_DATA_WORDS = (
    # 动词 / 聚合口径
    "多少", "几个", "几笔", "几条", "几款", "几种", "总数", "合计", "总额", "总和", "平均", "最高", "最低",
    "最多", "最少", "最好", "最差", "最佳", "排名", "排在前", "前", "top", "占比", "比例", "分布", "趋势",
    "增长", "增速", "下滑", "下降", "同比", "环比", "统计", "汇总", "清单", "明细", "对比", "比较",
    # 时间说法（口语优先）
    "上个月", "上月", "这个月", "本月", "下个月", "去年", "前年", "今年", "近一个月", "近三个月", "近三个月",
    "近半年", "近一年", "近 30 天", "近30天", "近一周", "第一季度", "季度", "年度", "月度", "每周", "每天",
    "多久", "期间",
    # 业务对象 / 主题
    "客户", "患者", "用户", "订单", "交易", "持仓", "诊所", "医生", "科室", "就诊", "住院", "门诊", "药品",
    "库存", "体检", "账单", "结算", "费用", "收入", "营收", "收益", "净值", "利润", "成本", "亏损", "回撤",
    "套餐", "资费", "话费", "通话", "流量", "短信", "订购", "退订", "投诉", "客服", "理财", "基金", "保险",
    "保单", "理赔", "风险评级", "报表", "业绩", "存款", "贷款", "银行卡", "金额", "余额",
    # 动作 / 疑问
    "哪款", "哪家", "哪些", "哪个", "怎么样", "卖了", "销量", "数量", "人数", "预测", "forecast",
    "表格", "这张表", "第几行", "第几列", " select", "count", "sum(", "avg(",
)
_TRIVIAL_MAX = 6          # 太短的提问（"在吗"）不做理解
# 明确不需要理解的：打招呼、客套、纯算术
_CHAT_ONLY = ("你好", "您好", "在吗", "在不在", "谢谢", "多谢", "感谢", "再见", "拜拜", "早安", "早啊",
              "晚上好", "嗨", "hello", "hi ", "牛", "厉害", "棒")
_QUESTION_MARKS = ("多少", "几个", "多少家", "哪些", "哪个", "哪款", "哪家", "什么", "怎么", "如何",
                   "为什么", "是否", "能不能", "可以吗", "多久", "吗", "？", "?")


def worth_understanding(question: str) -> bool:
    """本地快速判断：这个问题是不是在「问数据」，值不值得花一次结构化调用。

    宁可多判一点（多一次便宜调用），也不要漏掉真正的数据问题；纯闲聊与纯算术必须拦住。
    """
    q = (question or "").strip()
    if not q:
        return False
    # 「它 / 这个 / 那…呢」这类追问最容易缺主语，最需要补全——放在长度判断之前
    if re.search(r"^(那|它|它们|这个|这些|还有|其它|其他|再)", q):
        return True
    if len(q) <= _TRIVIAL_MAX and not any(ch.isdigit() for ch in q):
        return False
    lower = q.lower()
    # 打招呼 / 客套：短且没有别的意图词
    if any(w in lower for w in _CHAT_ONLY) and len(q) <= 12 and not any(w in lower for w in _DATA_WORDS):
        return False
    # 强信号：出现业务对象或聚合口径词
    if any(word in lower for word in _DATA_WORDS):
        return True
    # 「它 / 这个 / 那…呢」这类追问最容易缺主语，优先补
    if re.search(r"^(那|它|它们|这个|这些|还有|其它|其他|再)", q):
        return True
    # 次强信号：带疑问标记的稍长提问
    if len(q) >= 6 and any(mark in lower for mark in _QUESTION_MARKS):
        return True
    return False


# --------------------------------------------------------------------------- #
# 结构化理解：一次便宜调用产出 QuerySpec
# --------------------------------------------------------------------------- #
UNDERSTAND_SYSTEM = """\
你是一个需求分析师，负责把用户的口语提问拆解成结构化的查询意图，供下游的数据查询 Agent 精确执行。

只输出一个 JSON 对象（不要代码块、不要解释），字段如下：
{
  "rewritten": "补全指代、消除口语后的完整问题（中文一句话，保留用户的原始口径要求）",
  "task_type": "lookup|aggregate|rank|trend|compare|forecast|rag|calc|chat|other",
  "database": "financial_asset_management|healthcare_analytics_competition|telecom_operations_db|tables|knowledge|空字符串表示不需要",
  "tables": ["推测要用的表 / 数据集（不确定就留空数组）"],
  "entities": ["问题里提到的具体实体取值，如客户名、产品名、地市"],
  "metrics": ["要算的指标，带定量口径：如 就诊费用合计、客户数(去重)"],
  "dimensions": ["分组 / 拆分维度，如 科室、套餐类型、月份"],
  "filters": ["筛选条件，如 仅限逾期、is_current=1"],
  "time_range": {"raw": "用户原话", "start": "YYYY-MM-DD 或空", "end": "YYYY-MM-DD 或空", "granularity": "day|week|month|quarter|year|空"},
  "aggregation": "SUM|COUNT|COUNT_DISTINCT|AVG|MAX|MIN|RATIO|LAG_RATIO|NONE",
  "order_limit": "排序与截断要求，如 按净额降序取前 10；没有就写 无",
  "ambiguities": ["这一问真正有歧义的地方，如 是否含退款、是否只看在售"],
  "assumptions": ["你建议采用的默认口径（回答时必须向用户说明）"],
  "sql_hints": ["给下游的关键提醒：用哪张表的哪个字段、日期列是什么类型、要不要去重"]
}

拆解准则：
1. **时间必须落成具体日期**：以 system 给的今天为准。"上个月"=上自然月、"近 30 天"=今天减 30 天、"去年"=上个自然年；粒度填 month/day/year 等。
2. **"oustanding 好 / 最 / 排名"必须写明排序字段与升降序**；没说明就选最合理的并在 assumptions 里声明。
3. **计数要说清去重**：问"多少笔/多少条"→ COUNT(记录)；问"多少客户/多少人/多少个"→ COUNT(DISTINCT 实体 id)。
4. **多轮追问要补主语**：结合 history 把"它 / 这个 / 那它的趋势呢"还原成完整对象，写进 rewritten。
5. **歧义如实列出**，不要为了看起来确定而编造；assumptions 给出最稳妥的默认口径。
6. 纯闲聊 / 打招呼 / 简单算术：task_type 填 chat 或 calc，其余字段留空即可。
"""

UNDERSTAND_USER = """\
今天是 {today}。

【最近对话（用于补全指代，越靠后越新）】
{history}

【本轮用户提问】
{question}

输出 JSON："""


def _loose_json(text: str) -> dict | None:
    """宽容地解析 JSON：容忍 ```json 代码块、前后寒暄、尾随逗号。"""
    if not text:
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    s = s[start:end + 1]
    for attempt in (s, re.sub(r",\s*([}\]])", r"\1", s)):
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _norm_list(value, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out, seen = [], set()
    for item in value:
        item = str(item).strip()
        if item and item not in ("无", "无。", "空", "null", "None") and item not in seen:
            seen.add(item)
            out.append(item[:80])
        if len(out) >= limit:
            break
    return out


def normalize(raw: dict) -> dict:
    """把模型返回的任意 JSON 收敛成结构一致的 QuerySpec（缺字段自动补空）。"""
    raw = raw or {}
    time_range = raw.get("time_range") if isinstance(raw.get("time_range"), dict) else {}
    spec = {
        "rewritten": str(raw.get("rewritten") or "").strip()[:200],
        "task_type": str(raw.get("task_type") or "other").strip().lower(),
        "database": str(raw.get("database") or "").strip(),
        "tables": _norm_list(raw.get("tables"), 6),
        "entities": _norm_list(raw.get("entities"), 8),
        "metrics": _norm_list(raw.get("metrics"), 6),
        "dimensions": _norm_list(raw.get("dimensions"), 6),
        "filters": _norm_list(raw.get("filters"), 6),
        "aggregation": str(raw.get("aggregation") or "NONE").strip().upper(),
        "order_limit": str(raw.get("order_limit") or "").strip()[:120],
        "ambiguities": _norm_list(raw.get("ambiguities"), 4),
        "assumptions": _norm_list(raw.get("assumptions"), 4),
        "sql_hints": _norm_list(raw.get("sql_hints"), 6),
        "time_range": {
            "raw": str(time_range.get("raw") or "").strip()[:60],
            "start": str(time_range.get("start") or "").strip()[:10],
            "end": str(time_range.get("end") or "").strip()[:10],
            "granularity": str(time_range.get("granularity") or "").strip().lower(),
        },
    }
    if spec["task_type"] not in KIND_LABELS:
        spec["task_type"] = "other"
    if spec["database"] not in DB_LABELS:
        spec["database"] = ""
    return spec


def understand(question: str, history: list[str] | None = None,
               now: datetime | None = None, complete=None) -> dict | None:
    """做一次查询理解。complete 是形如 f(system, user) -> str 的 LLM 调用函数（由 agent 注入）。

    失败（模型不可用 / 返回非 JSON）一律返回 None —— 上游拿到 None 就走原流程，不影响可用性。
    """
    if not enabled() or not question or complete is None:
        return None
    if not worth_understanding(question):
        return None
    now = now or datetime.now()
    ctx = "\n".join(str(h).strip()[:200] for h in (history or [])[-6:]) or "（无）"
    user = UNDERSTAND_USER.format(today=f"{now:%Y-%m-%d}", history=ctx, question=question.strip()[:500])
    try:
        raw = complete(UNDERSTAND_SYSTEM, user)
    except Exception:
        return None
    data = _loose_json(raw)
    if not data:
        return None
    spec = normalize(data)
    return spec if (spec["rewritten"] or spec["metrics"] or spec["tables"]) else None


# --------------------------------------------------------------------------- #
# 渲染成注入提示词的一段（紧凑、可读、可被模型当作"参考"而非"圣旨"）
# --------------------------------------------------------------------------- #
def render(spec: dict | None) -> str:
    """把 QuerySpec 渲染成注入本轮 System Prompt 的一段提示；无内容返回空串。"""
    if not spec:
        return ""
    lines = ["【查询理解（预先解析，用于对齐口径；与 get_table_schema / describe_table 的真实结构冲突时，一律以真实结构为准）】"]
    if spec.get("rewritten"):
        lines.append(f"· 改写后的完整问题：{spec['rewritten']}")
    kind = KIND_LABELS.get(spec.get("task_type", ""), "")
    db = DB_LABELS.get(spec.get("database", ""), spec.get("database", ""))
    if kind or db:
        lines.append(f"· 任务类型：{kind or '其它'}" + (f"　目标数据源：{db}" if db else ""))
    for key, label in (("metrics", "要算的指标"), ("dimensions", "分组维度"),
                       ("entities", "涉及实体"), ("filters", "筛选条件")):
        items = spec.get(key) or []
        if items:
            lines.append(f"· {label}：{'、'.join(items)}")
    tr = spec.get("time_range") or {}
    if tr.get("raw") or tr.get("start") or tr.get("end"):
        span = " ~ ".join(x for x in (tr.get("start"), tr.get("end")) if x)
        gran = {"day": "按天", "week": "按周", "month": "按月", "quarter": "按季度", "year": "按年"}.get(
            tr.get("granularity", ""), "")
        lines.append(f"· 时间范围：{tr.get('raw') or '（未明说）'}"
                     + (f" → {span}" if span else "")
                     + (f"（{gran}）" if gran else ""))
    agg = spec.get("aggregation") or "NONE"
    if agg and agg != "NONE":
        agg_cn = {"COUNT_DISTINCT": "去重计数 COUNT(DISTINCT …)", "RATIO": "算占比（分组计数或金额再除整体）",
                  "LAG_RATIO": "取相邻两期后算变化率", "SUM": "求和 SUM", "COUNT": "计数 COUNT",
                  "AVG": "平均 AVG", "MAX": "取最大 MAX", "MIN": "取最小 MIN"}.get(agg, agg)
        lines.append(f"· 聚合方式：{agg_cn}")
    if spec.get("order_limit") and spec["order_limit"] != "无":
        lines.append(f"· 排序与截断：{spec['order_limit']}")
    if spec.get("tables"):
        lines.append(f"· 可能用到的表：{'、'.join(spec['tables'])}（仍需用表结构工具核对）")
    if spec.get("sql_hints"):
        lines.append("· 写法提示：" + "；".join(spec["sql_hints"]))
    if spec.get("ambiguities"):
        lines.append("· 已识别歧义：" + "；".join(spec["ambiguities"]))
    if spec.get("assumptions"):
        lines.append("· 默认口径（**回答时必须用一句话向用户说明**）：" + "；".join(spec["assumptions"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 两块清单式约束：写 SQL 前必查 / 回答前必查
# --------------------------------------------------------------------------- #
SQL_GUARDRAILS = """\
<sql_guardrails title="写 SQL 前必查清单（逐条对照，违反任意一条都会答错）">
1. 【先核对真实表结构】列名必须来自 get_table_schema / describe_table 的真实返回，凭印象编列名是最主要的失败原因；技能卡里的模板 SQL 仅供参考，冲突时以真实结构为准。
2. 【取值不确定的字段要先看再筛】写 WHERE type='…' 之前，若拿不准取值域（如高等级客户是 'gold' 还是 'VIP'），先 SELECT DISTINCT 该列 LIMIT 20 看真实取值，再写条件——比写错再改便宜得多。
3. 【计数要说清去重】"多少笔/条/次" → COUNT(记录)；"多少客户/人/种/个" → COUNT(DISTINCT 实体主键)。同一批回答里两个口径不能混用。
4. 【时间按真实日期列过滤】不要对日期列套字符串模糊匹配；月度聚合按其类型取 YYYY-MM（金融 VARCHAR ISO 串用 LEFT(col,7)，医疗 DATETIME 用 DATE_FORMAT(col,'%Y-%m')）；跨库联合或一个回答里多个查询要统一时间口径。
5. 【排序类问题必须写明排序字段与 LIMIT】"最好/最贵/排名前 N" → 先限定范围（在售/有效），再 ORDER BY 目标字段 + LIMIT N，并明确是取最大还是最小。
6. 【左右连接与空值】COUNT(col) 会跳过 NULL，想要分母请用 COUNT(*) 或 COUNT(DISTINCT 主键)；LEFT JOIN 后用聚合注意一对多放大，必要时先按主键去重再算。
7. 【金额与比率精度】金额聚合保留两位（ROUND(x,2)），比率乘 100 后保留一位；整数除法先乘 1.0。
8. 【大集合先聚合后返回】明细超过 50 行就先 GROUP BY/COUNT 概览，再按需取 TopN；宁可多查一次聚合，也不要把上万行塞进上下文。
9. 【一次只想一件事】两个问题（既有总数又要 TopN）拆成两条 SQL 各查一次，不要塞进一条复杂语句里相互干扰。
10. 【结果异常先自检】返回空 / 只有一行 / 数量级明显不对（如金额个位）时，先怀疑口径与时间范围，核对后重查，不要把可疑结果直接写进回答。
</sql_guardrails>"""

ANSWER_DISCIPLINE = """\
<answer_discipline title="回答前必查清单（数据类回答的硬要求）">
1. 【只用查到的数字】回答里的每个数字都必须能在工具返回结果里找到来源；工具没返回、没查到的绝不写出来。不得"合理推测"一个具体数值。
2. 【说清口径】这句话回答的是哪个口径要讲明白：时间范围（如"2024 自然年"）、去重方式（"按客户去重"）、是否含特殊状态（"含退订"）。尤其是**存在歧义并按默认假设处理时，必须点明假设**。
3. 【单位与数量级】金额带单位（元 / 万元），比率带 %；整数百分比也保留一位小数，避免让人误以为是精确比分。
4. 【异常要说】数据明显偏少 / 结果被截断 / 某些维度为空时，如实提示一句，并给出可行的解决办法（换条件、分组再查）。
5. 【不多答】问什么答什么；用户没问趋势就不要顺手预测，没问原因就别编原因（"可能因为…"这类只有依据充分时才说）。
6. 【失败不空转】取数失败时讲清原因 + 给替代方案，不要连着重试同一个错误写法。
</answer_discipline>"""


def guardrails_block(database_ready: bool = True, tables_ready: bool = True) -> str:
    """按当前可用数据源拼出清单区块（没有的工具就不提，省得模型去调不存在的工具）。"""
    block = SQL_GUARDRAILS
    block = block.replace("get_table_schema / describe_table",
                          "get_table_schema" if not tables_ready else "get_table_schema / describe_table")
    return "\n\n" + block + "\n\n" + ANSWER_DISCIPLINE


# --------------------------------------------------------------------------- #
# 自检：python prompting.py
# --------------------------------------------------------------------------- #
def _demo() -> None:
    print("QUND 开关：", enabled())
    for q in ["在吗", "你好呀", "上个月哪个套餐卖得最好", "那它的趋势呢", "2024 年就诊费用比前一年多了多少"]:
        print(f"  是否做理解 {q!r:28} -> {worth_understanding(q)}")

    fake = {
        "rewritten": "2024 自然年各科室的就诊费用合计排名 Top10（按结算净额口径）",
        "task_type": "rank",
        "database": "healthcare_analytics_competition",
        "tables": ["medical_encounters"],
        "entities": [],
        "metrics": ["就诊费用合计 SUM(total_cost)"],
        "dimensions": ["科室 department"],
        "filters": ["仅 2024 年"],
        "time_range": {"raw": "2024 年", "start": "2024-01-01", "end": "2024-12-31", "granularity": "month"},
        "aggregation": "SUM",
        "order_limit": "按费用合计降序取前 10",
        "ambiguities": ["费用是含药品还是只算诊疗"],
        "assumptions": ["按 encounter 发生日期统计、含全部科室"],
        "sql_hints": ["日期列是 DATETIME，可直接比较", "金额列 SUM 后 ROUND 两位"],
    }
    print("\n渲染结果：\n" + render(normalize(fake)))

    # 容错：代码块 + 尾随逗号 + 寒暄
    messy = '好的，结果如下：\n```json\n{"rewritten": "查医疗库的客户数", "task_type": "aggregate", "aggregation": "COUNT_DISTINCT",}\n```\n以上。'
    print("\n容错解析：", normalize(_loose_json(messy))["aggregation"])


if __name__ == "__main__":
    _demo()
