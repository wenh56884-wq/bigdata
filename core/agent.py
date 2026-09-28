"""带 Checkpointer 对话记忆的 LangChain Agent —— 支持多会话（多重对话）。

设计要点
--------
1. **一个会话 = 一个 thread_id**：Checkpointer 以 `thread_id` 为键隔离并保存完整消息
   历史，不同会话之间上下文互不可见，切换回去还能接着聊。
2. **Checkpointer 落盘**：优先 `SqliteSaver`（写到 `data/checkpoints.sqlite3`），
   服务重启后历史仍在；依赖缺失时自动退回 `MemorySaver`（进程内有效）。
3. **会话元数据单独存**：标题 / 创建时间 / 更新时间 / 消息数存在
   `data/conversations.json`，避免为了列目录而加载全部消息。
4. **并发安全**：Flask 默认多线程，这里用一个锁把图调用串行化，避免 SQLite 写冲突。
5. **流式输出（打字机）**：`create_agent` 内部节点只走 `invoke`，逐 token 输出
   由 `stream_ask()` 在 Agent 之外自己跑“绑定工具的 ReAct 循环”，结束时用
   `graph.update_state()` 把本回合写回 Checkpointer，记忆与历史不受影响。
6. **System Prompt 与 Dynamic Prompt**：固定规则见 `_BASE_PROMPT`；`build_system_prompt()`
   每次问答前渲染一次（把当前时间等变量拼进模板），动态注入模型。
7. **跨会话存储（LangGraph Store）**：Checkpointer 只保存“单场对话”，会话间互不可见；
   另外启用全局共享的 `SqliteStore`（`data/memory.sqlite3`）做长期记忆，任意会话都能用
   `remember` / `recall` / `forget` 读写同一份事实，真正做到“换个会话还记得”。
8. **规划（Planning）**：复杂问题先由规划器拆成 2~6 步执行计划（`planning.py`），注入
   System Prompt 后按步推进；模型每完成一步用 `update_plan` 勾选（用户能实时看到进度），
   终答前再由自检器（Reflector）核对计划是否真的完成，没完成就补一轮继续执行。
   简单问题（算术、单次查询等）由启发式判断后**跳过规划**，不多花一次模型调用。
9. **分层记忆（Memory）**：① 会话内 Checkpointer（消息历史）；② 跨会话 Store
   （带类型 / 标签 / 重要度的长期事实，按相关度召回）；③ 长会话自动摘要压缩
   （`MEM_COMPACT`，超长对话把早期消息压成摘要 + 保留最近若干条），三层配合让
   上下文“既记得住、又不爆炸”。

> Agent = LLM(大脑) + Planning(规划) + Tool use(执行) + Memory(记忆)：
> 大脑 = ChatOpenAI（多服务商自动切换）；规划 = planning.py + 本轮计划注入 + 自检闭环；
> 执行 = 14+ 工具（SQL / 知识库 / 画图 / 预测 / 计划 / 记忆）；记忆 = 会话/跨会话/摘要三层。
"""

import ast
import argparse
import contextvars
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from services.rag import PER_LIST as RAG_PER_LIST
from services.rag import TOP_K as RAG_TOP_K
from services.rag import RagService
from services.rag import tokenize as rag_tokenize  # 中文友好的分词（长期记忆按相关度召回时复用）

from core import planning  # 规划引擎：任务拆解 / 执行自检 / 深度搜索拆解（Planning 模块）
from core import prompting  # 提示词工程：查询意图结构化理解（Query Understanding）+ SQL / 回答清单
from core import reasoning  # 推理层：CoT / ToT 树状多路径 / MCTS 规划搜索 / Reflexion 反思记忆
from core import context  # 上下文工程：提示分层合成 / 工具动态注册 / 检索上下文管线 / 上下文度量
from services import tables  # 非结构化表格：把 非结构化数据/ 的 markdown/HTML 表格与 Excel/CSV 文件解析成可 SQL 查询的 SQLite
from services import ml_forecast  # sklearn 月度业务指标预测（三个库）
from services import sanitize  # 输出脱敏：结果集预处理 + 回答 / 流式文本兜底，避免个人信息出现在回答里
from services import pysandbox  # 受限 Python 计算沙箱：给 Agent 一个「用 Python 算」的能力
from services import ml_insight  # 数据洞察：统计画像 / 相关分析 / 异常检测 / 聚类挖掘

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite3"
DEFAULT_TITLE = "新的对话"
TITLE_MAX_LEN = 20

# 全局共享的知识库服务（knowledge/ 目录，懒构建索引）
rag_service = RagService()


# --------------------------------------------------------------------------- #
# MySQL 数据查询支持
# 三个业务库：financial_asset_management（金融）、
# healthcare_analytics_competition（医疗）、telecom_operations_db（通信）
# --------------------------------------------------------------------------- #
DB_CATALOG = {
    "financial_asset_management": {
        "clients", "managers", "products", "counterparties", "portfolios",
        "transactions", "holdings", "risk_metrics",
    },
    "healthcare_analytics_competition": {
        "patient_master_index", "medical_encounters", "medical_orders",
        "pharmacy_inventory", "medical_equipment_usage", "medical_staff",
        "departments_wards", "billing_transactions",
    },
    "telecom_operations_db": {
        "customers", "products", "subscriptions", "cdr_detail",
        "monthly_bills", "marketing_campaigns", "service_records", "network_resources",
    },
}
# 表名 → 所在库（用于把“裸表名”自动解析到正确的库执行）
_TABLE_DBS: dict[str, set[str]] = {}
for _db_name, _tabs in DB_CATALOG.items():
    for _tab in _tabs:
        _TABLE_DBS.setdefault(_tab, set()).add(_db_name)

_READONLY_PREFIXES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|replace\s+into|"
    r"load\s+data|load_file|load\s+file|outfile|dumpfile|sys_exec|sys_eval|"
    r"lock|kill|call|shutdown|backup|restore|use)\b",
    re.IGNORECASE,
)


def db_config() -> dict:
    """MySQL 连接配置，可用 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD 覆盖（见 .env）。"""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": _env_int("DB_PORT", 3306, minimum=1, maximum=65535),
        "user": os.getenv("DB_USER", "root"),
        # Keep compatibility with the bundled local demo database. Production
        # deployments should always override this through DB_PASSWORD.
        "password": os.getenv("DB_PASSWORD") or "123456",
        "charset": "utf8mb4",
        "connect_timeout": 8,
        "read_timeout": 30,
    }


def db_connect(database: str | None = None):
    """创建 MySQL 连接（pymysql 懒加载，缺失时报清晰的错误）。"""
    try:
        import pymysql
    except ImportError:
        raise RuntimeError("缺少 pymysql，请先执行：pip install pymysql")
    conf = db_config()
    if database:
        conf["database"] = database
    return pymysql.connect(**conf)


def _strip_quoted(sql: str) -> str:
    """抹掉字符串字面量，避免把值里的词误认成表名。

    反引号包裹的是标识符不是值：去掉反引号保留原名，让 `库名`.`表名`
    这类写法也能被 _detect_database 正确解析。
    """
    sql = re.sub(r"'[^']*'|\"[^\"]*\"", " ", sql)
    return re.sub(r"`([^`]*)`", r"\1", sql)


_DB_QUAL_RE = re.compile(
    r"\b(financial_asset_management|healthcare_analytics_competition|telecom_operations_db)"
    r"\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)"
)


def _detect_database(sql: str) -> tuple[str | None, str]:
    """根据语句里的表名推断唯一库。返回 (库名, 提示/错误)。

    优先认 库名.表名 的显式限定：`products` 等表在金融/通信两个业务库同名，
    只有显式限定（telecom_operations_db.products）才能消除歧义——
    不能因为交集有多个库就反过来要求“写成 库名.表名”，否则正确的限定写法会一直被拒。
    没有显式限定再按“裸表名所在库交集”推断。
    """
    body = _strip_quoted(sql)
    qualified = _DB_QUAL_RE.findall(body)
    if qualified:
        dbs = {db for db, _tbl in qualified}
        if len(dbs) > 1:
            return None, (
                "语句用 库名.表名 同时指定了多个库：" + "、".join(sorted(dbs)) + "，请统一限定到同一个库。"
            )
        return dbs.pop(), ""
    found = {tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", body) if tok in _TABLE_DBS}
    if not found:
        return None, "（未识别到业务表名；可先运行 list_database_tables 查看三个库的表）"
    inter = set.intersection(*(_TABLE_DBS[t] for t in found))
    if len(inter) == 1:
        return inter.pop(), ""
    if not inter:
        return None, f"语句引用了分属不同库的表：{', '.join(sorted(found))}，请统一为 库名.表名 写法。"
    dup = ", ".join(sorted(t for t in found if len(_TABLE_DBS[t]) > 1))
    return None, f"表名 {dup} 在多个库都存在，请写成 库名.表名（可选库：{', '.join(sorted(inter))}）。"


def _sql_probe(sql: str) -> str:
    """把语句还原成“语法骨架”：抹掉字符串字面量、反引号标识符与注释。

    只保留真实关键字与符号，用于只读校验——避免把值/列名/注释里的词
    （如 'drop' 字符串、`desc` 列名、注释里的 update）误判成写操作或分号。
    """
    s = re.sub(r"'[^']*'|\"[^\"]*\"", " ", sql)  # 字符串字面量
    s = re.sub(r"`[^`]*`", " ", s)  # 反引号标识符（保留字列名是合法写法）
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)  # 块注释（含 /*!50000 … */）
    s = re.sub(r"--[^\n]*", " ", s)  # MySQL 行注释
    s = re.sub(r"#[^\n]*", " ", s)  # MySQL 行注释
    return s


def _validate_readonly(sql: str) -> str:
    """校验并归一化只读语句；不合法时抛出 ValueError。"""
    stmt = (sql or "").strip()
    if not stmt:
        raise ValueError("SQL 不能为空")
    body = stmt.rstrip(";").strip()
    probe = _sql_probe(body)
    if ";" in probe:
        raise ValueError("只允许单条只读语句，不支持分号分隔的多语句")
    head = probe.split(None, 1)[0].upper()
    if head not in _READONLY_PREFIXES:
        raise ValueError(f"只允许执行只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN/WITH），不允许 {head}")
    if _WRITE_KEYWORDS.search(probe):
        raise ValueError("检测到写操作或危险关键字，已拒绝执行")
    return body


def _rows_to_text(headers: list[str], rows: list[tuple], shown: int = 200) -> str:
    def _cell(v) -> str:
        if v is None:
            return "NULL"
        s = str(v)
        return s if len(s) <= 100 else s[:100] + "…"

    lines = [" | ".join(str(h) for h in headers)]
    for row in rows[:shown]:
        lines.append(" | ".join(_cell(v) for v in row))
    if len(rows) > shown:
        lines.append(f"…共 {len(rows)} 行，仅显示前 {shown} 行。")
    if not rows:
        lines.append("（查询成功，无数据返回）")
    return "\n".join(lines)


# “最近一次成功查询”缓存：execute_sql / query_tables 写入，plot_last_result 据此画图
_LAST_QUERY: dict = {"headers": [], "rows": [], "db": ""}


# --------------------------------------------------------------------------- #
# 数据来源（Provenance）：本轮回答真正用到的数据出处，随回答一起回给前端展示
# --------------------------------------------------------------------------- #
# 为什么要单独收集：工具的返回值是给模型看的文本，用户只看到最终结论，
# 不知道这些数字来自哪个库 / 哪张表 / 哪个文档。这里在工具侧顺手登记出处，
# 整轮结束后由 stream_ask 以 sources 事件下发，界面在回答下方展示。
_SOURCE_KINDS = {
    "database": "MySQL 业务库",
    "tables": "非结构化表格库",
    "knowledge": "知识库文档",
    "forecast": "机器学习预测",
    "chart": "生成图表",
}
_DB_SOURCE_LABEL = {
    "financial_asset_management": "MySQL 业务库 · 金融",
    "healthcare_analytics_competition": "MySQL 业务库 · 医疗",
    "telecom_operations_db": "MySQL 业务库 · 通信",
}
_DB_SHORT = {
    "financial_asset_management": "金融库",
    "healthcare_analytics_competition": "医疗库",
    "telecom_operations_db": "通信库",
}
_ROUND_SOURCES: list[dict] = []
_sources_lock = threading.RLock()


def reset_sources() -> None:
    """开始新一轮问答时清空来源清单（ReAct 循环全程持锁，同一时刻只有一轮在跑）。"""
    with _sources_lock:
        _ROUND_SOURCES.clear()


def take_sources() -> list[dict]:
    """取出本轮累积的全部数据来源（按出现顺序）。"""
    with _sources_lock:
        return [dict(item) for item in _ROUND_SOURCES]


def _sanitize_message(msg):
    """把一条消息里的文本换成脱敏版（保留 tool_calls 等其余字段）。

    作用范围不止"给用户看"，还包括写回 Checkpointer 的历史：历史上留存明文，
    下次压缩/摘要时又会被喂回上下文，等于没脱。从源头替换更干净。
    """
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content:
        masked = sanitize.mask_text(content)
        if masked != content:
            try:
                return msg.model_copy(update={"content": masked})
            except Exception:  # 不是 pydantic 模型（老版本 / 自定义对象）
                try:
                    msg.content = masked
                except Exception:
                    pass
    return msg


def record_source(kind: str, name: str, label: str = "", tables: list[str] | None = None,
                  rows: int | None = None, detail: str = "", sql: str = "") -> None:
    """登记一条数据来源；同一出处（kind + name）只留一条：表名累计，行数与 SQL 取最后一次。"""
    label = label or _SOURCE_KINDS.get(kind, "数据来源")
    tables = [str(t) for t in (tables or []) if t]
    detail = (detail or "").strip()
    # 出处里的 SQL / 描述是要**展示给用户看的**：where 条件里常带着手机号、证件号，
    # 这里统一脱敏，避免"数据脱了敏、SQL 又把明文漏出来"
    detail = sanitize.mask_text(detail)
    sql = sanitize.mask_text((sql or "").strip())
    with _sources_lock:
        for old in _ROUND_SOURCES:
            if old.get("kind") == kind and old.get("name") == name:
                # 同一出处多次取数：表名累计，行数/SQL 以最后一次为准（最终答案通常来自最后那次查询）
                for tab in tables:
                    if tab not in old["tables"]:
                        old["tables"].append(tab)
                if rows is not None:
                    old["rows"] = rows
                if detail and detail not in (old.get("detail") or ""):
                    merged = ((old.get("detail") or "") + " · " + detail).strip(" ·")
                    old["detail"] = merged[:300]
                if sql:
                    old["sql"] = sql[:300]
                return
        _ROUND_SOURCES.append({
            "kind": kind, "label": label, "name": name, "tables": tables,
            "rows": rows, "detail": detail[:300], "sql": sql[:300],
        })


def _sql_tables_used(sql: str, database: str) -> list[str]:
    """从只读业务 SQL 里提取用到的表名（去重保序，不含别名/子查询残留词）。"""
    used: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", _strip_quoted(sql)):
        if token in DB_CATALOG.get(database, ()) and token not in used:
            used.append(token)
    return used


@tool
def execute_sql(sql: str) -> str:
    """对本地 MySQL 执行【只读】SQL（SELECT / SHOW / DESCRIBE / EXPLAIN / WITH），返回表格式查询结果。
    可用于查三个业务库：financial_asset_management（金融）、healthcare_analytics_competition（医疗）、
    telecom_operations_db（通信）。裸表名会自动解析到唯一所属库；跨库或有同名表时请用 库名.表名。
    用查询结果回答用户即可，不要凭空编造数据。

    【正例 / 反例 —— 照着正例写】
    问“有多少客户” → 反例 SELECT COUNT(client_id) clients（没去重，重复的客户会重复计数）
                    正例 SELECT COUNT(DISTINCT client_id) AS c FROM financial_asset_management.clients
    问“最贵的套餐” → 反例 SELECT * FROM products ORDER BY base_fee（少了范围与方向，可能把退订套餐也算进来）
                    正例 SELECT product_name, base_fee AS 月租 FROM telecom_operations_db.products
                         WHERE is_current=1 ORDER BY base_fee DESC LIMIT 1
    问“近半年每月收入” → 反例 WHERE date >= '2024-06'（把日期当字符串比，且没有按自然月聚合）
                    正例 SELECT 月份表达式 AS ym, SUM(金额列) FROM … WHERE ym BETWEEN '2024-07' AND '2024-12'
                         GROUP BY ym ORDER BY ym
                        ——月份表达式看库：金融库是 VARCHAR 的 ISO 串用 LEFT(col,7)，医疗库是真 DATETIME 用 DATE_FORMAT(col,'%Y-%m')
    写成之前先问自己：列名真实存在吗？计数去重复了吗？时间范围对吗？方向（最大/最小）对吗？"""
    try:
        body = _validate_readonly(sql)
        database, hint = _detect_database(body)
        if database is None:
            # 无法自动确定库：给出指引，避免裸跑报 “No database selected”
            return (
                "无法自动确定所在库：" + hint.rstrip("。！？. ") +
                "。请改用 库名.表名 的写法重试，例如：SELECT COUNT(*) FROM financial_asset_management.clients;"
            )
        conn = db_connect(database)
        try:
            with conn.cursor() as cur:
                cur.execute(body)
                headers = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
        finally:
            conn.close()
        # ① 脱敏：结果集在喂给模型之前就按列名 + 值双重判断抹掉个人信息
        #    （图表工具复用同一份缓存，画出来的图同样不含明文）
        headers, rows, masked_cols = sanitize.mask_rows(headers, list(rows))
        sanitize_note = sanitize.note_for(masked_cols)
        # 缓存最近一次查询结果，供 plot_last_result 画图（限制前 1000 行）
        _LAST_QUERY["headers"] = [str(h) for h in headers]
        _LAST_QUERY["rows"] = list(rows)[:1000]
        _LAST_QUERY["db"] = database
        # 数据来源：把“这些数字出自哪个库的哪些表”登记下来，随回答展示给用户
        record_source(
            "database", database,
            label=_DB_SOURCE_LABEL.get(database, "MySQL 业务库"),
            tables=_sql_tables_used(body, database), rows=len(rows), sql=body[:300],
        )
        text = _rows_to_text(headers, rows) + f"\n（在 {database} 库执行）"
        return text + (f"\n{sanitize_note}" if sanitize_note else "")
    except Exception as exc:
        return f"执行失败：{exc}"


@tool
def plot_last_result(title: str = "", x_col: str = "", y_cols: str = "") -> str:
    """把“最近一次查询结果”画成图表（Matplotlib，折线/柱状自动选择），
    返回图片引用地址，供最终回答直接在网页上展示。
    数据来源可以是业务库（execute_sql，MySQL）或非结构化表格库（query_tables，SQLite），
    两者都会自动记住最近一次查询结果，无需重复取数。

    适用：用户要求可视化 / 画图 / 看走势 / 看占比分布，且需要基于刚查出的数据作图时
    （按 先取数 → 再 plot_last_result 画图 的顺序调用）。

    title=图的标题；x_col=横轴列名（默认自动选日期/名称类列）；
    y_cols=要画的数值列名（多个用英文逗号分隔；默认自动选所有数值列）。"""
    cap = _LAST_QUERY
    if not cap["rows"]:
        return "暂无可绘图数据：请先用 execute_sql（业务库）或 query_tables（表格库）查询数据，再调用本工具画图。"
    headers, rows = cap["headers"], cap["rows"]

    def _idx(name: str) -> int:
        name = (name or "").strip()
        for i, h in enumerate(headers):
            if h == name:
                return i
        return -1

    def _numeric(idx: int) -> bool:
        ok = tot = 0
        for r in rows:
            if idx >= len(r) or r[idx] is None:
                continue
            tot += 1
            try:
                float(str(r[idx]))
                ok += 1
            except (TypeError, ValueError):
                pass
        return tot > 0 and ok >= tot * 0.8

    numeric = [i for i in range(len(headers)) if _numeric(i)]
    if not numeric:
        return "查询结果里没有可绘图的数值列。"
    xi = _idx(x_col)
    if xi < 0:
        xi = next((i for i in range(len(headers)) if i not in numeric), None)
        if xi is None:
            xi = 0
    yi = []
    if y_cols.strip():
        for name in y_cols.split(","):
            j = _idx(name)
            if j >= 0 and j != xi:
                yi.append(j)
    if not yi:
        yi = [i for i in numeric if i != xi]
    if not yi:
        return "数值列与横轴列相同，无法成图；请用 y_cols 明确指定要画的数值列。"

    try:
        from services import viz
    except ImportError:
        return "可视化不可用：缺少 matplotlib，请先执行 pip install matplotlib。"

    series = [{"name": headers[j], "values": []} for j in yi]
    x_labels = []
    seen = set()
    for r in rows[:200]:
        if xi >= len(r):
            continue
        label = "" if r[xi] is None else str(r[xi])
        if not label or label in seen:
            continue
        seen.add(label)
        vals = []
        ok = True
        for j in yi:
            v = r[j] if j < len(r) else None
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                ok = False
                break
        if not ok:
            continue
        x_labels.append(label)
        for s, v in zip(series, vals):
            s["values"].append(v)
        if len(x_labels) >= 150:
            break

    if not x_labels or not any(s["values"] for s in series):
        return "未能解析出可绘图的数值（请确认查询结果里含数值列）。"
    chart_title = title or f"{headers[xi]} 与 {' / '.join(s['name'] for s in series)}"
    path = viz.plot_query(chart_title, x_labels, series, ylabel="数值", prefix="chat")
    if not path:
        return "图表生成失败（请确认已安装 matplotlib：pip install matplotlib）。"
    fname = path.name
    # 数据来源：图也是“数据”，把它的取数出处一并登记（cap["db"] 可能是业务库名或 tables）
    record_source(
        "chart", fname, rows=len(x_labels),
        detail=f"图表《{chart_title}》，数据来自 {cap.get('db') or '最近一次查询'}",
    )
    return (
        f"已生成图表：{chart_title}（{len(x_labels)} 个数据点）。最终回答中请直接引用：\n"
        f"![{chart_title}](/reports/{fname})\n（图片文件：reports/{fname}）"
    )


@tool
def list_database_tables() -> str:
    """列出本地 MySQL 三个业务库的全部表名：金融 financial_asset_management、医疗
    healthcare_analytics_competition、通信 telecom_operations_db，用于确定 SQL 的库名表名。
    确定要查哪些表后，应调用 get_table_schema 查看这些表的真实字段，再据此写 SQL。"""
    lines = []
    for db, tabs in DB_CATALOG.items():
        lines.append(f"- {db}：{', '.join(sorted(tabs))}")
    lines.append("提示：语句可写 库名.表名；裸表名只有在不重名时才能自动识别。字段名请用 get_table_schema 查看真实结构。")
    return "\n".join(lines)


# 库名常见别名 → 真实库名（宽松识别“医疗库 / healthcare”等说法）
_DB_ALIASES = {
    "financial": "financial_asset_management",
    "finance": "financial_asset_management",
    "金融": "financial_asset_management",
    "healthcare": "healthcare_analytics_competition",
    "medical": "healthcare_analytics_competition",
    "医疗": "healthcare_analytics_competition",
    "telecom": "telecom_operations_db",
    "通信": "telecom_operations_db",
}


def _resolve_db_name(name: str) -> str | None:
    """把库名（含别名）归一化成 DB_CATALOG 里的真实 key。"""
    key = (name or "").strip().lower()
    if not key:
        return None
    for real in DB_CATALOG:
        if real.lower() == key:
            return real
    return _DB_ALIASES.get(key)


@tool
def get_table_schema(table: str = "", database: str = "") -> str:
    """读取本地 MySQL 业务库的【真实表结构】：字段名、类型、是否可空、键、默认值与注释，
    供写 SQL 前核对字段拼写与业务含义。

    用法：
    - 查单张表：get_table_schema(table="medical_encounters") 或
      get_table_schema(table="healthcare_analytics_competition.medical_encounters")；
    - 看整库（表名留空、给库名）：get_table_schema(database="healthcare_analytics_competition")。

    表名列名必须与它返回的真实结构完全一致，禁止凭印象编造列名；
    MySQL 里不存在的表 / 字段会明确提示“查无此列 / 无此表”。"""
    db_given = _resolve_db_name(database)
    tbl = (table or "").strip()
    if "." in tbl:
        head, _, tail = tbl.partition(".")
        if not db_given:
            db_given = _resolve_db_name(head)
        tbl = tail.strip()

    # 只给了裸表名：优先自动归属到唯一库
    if not db_given and tbl:
        owners = _TABLE_DBS.get(tbl.lower())
        if owners is None:
            return (
                f"在三个业务库里都没找到表 {tbl!r}。可先运行 list_database_tables 查看全部表名，"
                "或用 库名.表名 / database 参数指明所在库。"
            )
        if len(owners) == 1:
            db_given = next(iter(owners))
        else:
            return (
                f"表 {tbl} 在多个库都存在：{', '.join(sorted(owners))}，"
                "请写成 库名.表名 或传 database 参数指定其中一个。"
            )

    if not db_given:
        return (
            "库名没确定。可运行 list_database_tables 查看三个业务库，"
            "或用 get_table_schema(table='库名.表名') / get_table_schema(database='库名') 明确指定。"
        )

    try:
        conn = db_connect(db_given)
    except Exception as exc:
        return f"连接 MySQL 失败：{exc}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, table_comment FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (db_given,),
            )
            tables = {t: (c or "").strip() for t, c in cur.fetchall()}
            if tbl and tbl.lower() not in {t.lower() for t in tables}:
                return f"库 {db_given} 中不存在表 {tbl!r}，可用 list_database_tables 查看该库的表。"

            def _describe(name: str) -> list[str]:
                cur.execute(
                    "SELECT column_name, column_type, is_nullable, column_key, column_default, "
                    "column_comment FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (db_given, name),
                )
                rows = cur.fetchall()
                out = [f"### {db_given}.{name}" + (f"（{tables[name]}）" if tables.get(name) else "")]
                for col, ctype, nullable, ckey, default, comment in rows:
                    parts = [col, ctype]
                    flags = []
                    if ckey == "PRI":
                        flags.append("主键")
                    elif ckey == "UNI":
                        flags.append("唯一")
                    elif ckey == "MUL":
                        flags.append("索引")
                    if nullable == "NO":
                        flags.append("非空")
                    if default is not None:
                        flags.append(f"默认={default}")
                    if comment:
                        flags.append(f"注释:{comment}")
                    parts.append("/".join(flags) if flags else "-")
                    out.append("- " + " | ".join(parts))
                if not rows:
                    out.append("- （该表没有任何列）")
                return out

            if tbl:
                lines = _describe(tbl)
            else:
                lines = [f"# 库 {db_given} 共 {len(tables)} 张表："]
                for name in tables:
                    lines.extend(_describe(name))
            return "\n".join(lines)
    except Exception as exc:
        return f"读取表结构失败：{exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 数据库查询技能卡（skills/database/*.md）
# 每库一张卡：八张表速览 / 字段取值与业务口径 / 易错点 / 常用模板 SQL。
# Agent 判库后先加载对应技能卡再 get_table_schema 写 SQL，让 NL→SQL 更快更稳。
# --------------------------------------------------------------------------- #
SKILLS_DIR = PROJECT_ROOT / "skills" / "database"
_DB_SKILL_META = {
    "financial_asset_management": (
        "金融资产管理库",
        ["金融", "金融资产", "资产管理", "资管", "金融库", "finance", "financial"],
    ),
    "healthcare_analytics_competition": (
        "医院医疗数据分析库",
        ["医疗", "医院", "医院医疗", "医疗库", "医院库", "healthcare", "health", "hospital"],
    ),
    "telecom_operations_db": (
        "通信运营商库",
        ["通信", "运营商", "通信库", "运营商库", "telecom"],
    ),
}
# 第二类技能卡：非结构化表格库（skills/tables/），和业务库技能卡共用同一套加载机制
TABLE_SKILLS_DIR = PROJECT_ROOT / "skills" / "tables"
_TABLE_SKILL_META: dict[str, tuple[str, tuple[str, ...]]] = {
    "table_query": ("非结构化表格 · 表格查询", ("table_query", "表格查询", "单表查询", "tq")),
    "domain_ops": ("非结构化表格 · 领域运算", ("domain_ops", "领域运算", "运算", "ops")),
    "multi_step": ("非结构化表格 · 多步检索", ("multi_step", "多步检索", "多步", "msr")),
    # guide 放在最后：它的别名最宽（“表格/非结构化”），应当让具体数据集名先匹配
    "guide": ("非结构化表格 · 查询指南", ("guide", "指南", "表格指南", "非结构化", "表格", "tables", "table")),
}
_skill_cache: dict[Path, tuple[float, str]] = {}


def _match_db_skill_key(name: str) -> str | None:
    """把用户/模型给的名字归一化成技能卡对应的**业务库** key。"""
    name = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not name:
        return None
    for key in DB_CATALOG:
        if name == key or key in name or name in key:
            return key
    for key, (title, aliases) in _DB_SKILL_META.items():
        low_aliases = [a.lower() for a in aliases] + [title.lower()]
        if any(a and (a in name or name in a) for a in low_aliases):
            return key
    return None


def _match_table_skill_key(name: str) -> str | None:
    """把名字归一化成**非结构化表格库**的技能卡 key（table_query / domain_ops / multi_step / guide）。"""
    text = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    for key, (title, aliases) in _TABLE_SKILL_META.items():
        if key != "guide" and (text == key or key in text or text in key):
            return key
    # 先精确匹配别名（“表格”要落到 guide，而不是命中“表格查询”这个更长的别名），再退化为包含匹配
    for key, (title, aliases) in _TABLE_SKILL_META.items():
        low_aliases = [a.lower() for a in aliases] + [title.lower()]
        if any(a and a == text for a in low_aliases):
            return key
    for key, (title, aliases) in _TABLE_SKILL_META.items():
        low_aliases = [a.lower() for a in aliases] + [title.lower()]
        if any(a and (a in text or text in a) for a in low_aliases):
            return key
    return None


def _match_skill(name: str) -> tuple[str, str] | None:
    """统一解析技能卡名字，返回 (类别, key)：("database", 库名) 或 ("tables", 数据集名)。"""
    key = _match_db_skill_key(name)
    if key:
        return ("database", key)
    key = _match_table_skill_key(name)
    if key:
        return ("tables", key)
    return None


def _skill_path(family: str, key: str) -> Path:
    return (SKILLS_DIR if family == "database" else TABLE_SKILLS_DIR) / f"{key}.md"


def _read_skill(family: str, key: str) -> str | None:
    """读取技能卡 markdown（带 mtime 缓存，改文件后热更新）。"""
    path = _skill_path(family, key)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _skill_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    _skill_cache[path] = (mtime, text)
    return text


def list_db_skills() -> str:
    """列出全部可用技能卡（业务库 + 非结构化表格两族），供无参调用与排错时展示。"""
    lines = ["【MySQL 业务库技能卡】"]
    for key, (title, _) in _DB_SKILL_META.items():
        exists = "有" if (SKILLS_DIR / f"{key}.md").exists() else "缺"
        lines.append(f"- {key}（{title}）：{exists}")
    lines.append("【非结构化表格技能卡】")
    for key, (title, _) in _TABLE_SKILL_META.items():
        exists = "有" if (TABLE_SKILLS_DIR / f"{key}.md").exists() else "缺"
        lines.append(f"- {key}（{title}）：{exists}")
    return "\n".join(lines)


def db_skill_cards() -> list[dict]:
    """技能卡元数据（key + 中文名 + 是否就绪 + 类别），供 Web 端“手动指定技能卡”下拉动态填充。

    两个类别：kind=database（MySQL 三个业务库）与 kind=tables（非结构化表格库）。
    """
    cards = [
        {"key": key, "title": title, "kind": "database",
         "ready": (SKILLS_DIR / f"{key}.md").exists()}
        for key, (title, _) in _DB_SKILL_META.items()
    ]
    cards += [
        {"key": key, "title": title, "kind": "tables",
         "ready": (TABLE_SKILLS_DIR / f"{key}.md").exists()}
        for key, (title, _) in _TABLE_SKILL_META.items()
    ]
    return cards


def _manual_skill_hint(name: str) -> str:
    """用户在 Web 页面上手动选定某库技能卡 → 生成追加到当轮 System Prompt 的强制指令。

    返回空串表示“未指定 / 未识别”，走原来的“Agent 自己判断属于哪个库”默认流程。
    """
    match = _match_skill(name)
    if not match:
        return ""
    family, key = match
    if family == "database":
        title = _DB_SKILL_META[key][0]
        return (
            f"【手动指定数据范围】用户已在页面上把本次回答的数据范围指定为「{title}」（库 {key}）。"
            f"凡涉及业务数据统计/明细/报表类问题，一律按该库处理：先调用 get_db_skill(database='{key}') 加载技能卡，"
            f"再以 get_table_schema 返回的真实表结构为准查询，不要自行切换到其他库；"
            "仅当用户明确要求“跨库对比 / 三库分别统计 / 换成另一个库”时才按新指示执行。"
        )
    title = _TABLE_SKILL_META[key][0]
    scope = ("三个数据集的全部表格" if key == "guide"
             else f"数据集 {key} 里的表格")
    return (
        f"【手动指定数据范围】用户已在页面上把本次回答的数据范围指定为「{title}」（非结构化表格库，{scope}）。"
        f"凡涉及表格数据的问题，一律走表格链路：先调用 get_db_skill(database='{key}') 加载该技能卡，"
        f"再按 find_table → describe_table → query_tables 的顺序查询；"
        "不要改用 execute_sql 去查 MySQL（那些表里没有这批数据）；"
        "仅当用户明确要求换成业务库/知识库时才按新指示执行。"
    )


@tool
def get_db_skill(database: str = "") -> str:
    """加载查询技能卡（人工整理的口径、易错点与模板 SQL），两族都能加载：

    ① **MySQL 业务库**（financial_asset_management 金融 / healthcare_analytics_competition 医疗 /
       telecom_operations_db 通信）：八张表速览、字段取值与业务口径、易错点、模板 SQL；
       加载后先 get_table_schema 核对真实结构再写 SQL。
    ② **非结构化表格库**（guide 查询指南 / table_query 表格查询 / domain_ops 领域运算 /
       multi_step 多步检索）：库结构、表 id 规则、数值清洗约定、召回流程、实测易错点与模板 SQL；
       加载后按 find_table → describe_table → query_tables 走。

    参数 database：库名 / 数据集 key / 中文别名（如 '医疗'、'表格'、'多步检索'），留空返回全部技能卡清单。
    注意：技能卡仅供参考，与 get_table_schema（业务库）或 describe_table（表格库）返回的实时信息冲突时，
    一律以实时信息为准。"""
    match = _match_skill(database)
    if not match:
        return "没有匹配到技能卡，可用的库与技能卡：\n" + list_db_skills()
    family, key = match
    text = _read_skill(family, key)
    if not text:
        return (
            f"技能卡文件不存在或读取失败：{_skill_path(family, key)}\n"
            f"可用技能卡：\n{list_db_skills()}"
        )
    title = (_DB_SKILL_META if family == "database" else _TABLE_SKILL_META)[key][0]
    tip = ("写 SQL 前仍以 get_table_schema 返回的真实表结构为最终依据；冲突时一律以真实结构为准。"
           if family == "database" else
           "写 SQL 前仍以 describe_table 返回的实时列名与数值列为准；冲突时一律以实时信息为准。")
    return f"# 技能卡：{title}（{key}）\n\n> 提示：本卡为人工整理的口径与模板，{tip}\n\n" + text


# --------------------------------------------------------------------------- #
# NL→SQL 关键词抓取（analyze_query）：纯本地规则“抓关键字/关键提示词”，不查库、不耗 LLM
# 词典词均取自已核验的技能卡与语料，覆盖用户口语说法 → 库/表/字段的正确映射
# --------------------------------------------------------------------------- #
_NL_DB_LABEL = {
    "telecom_operations_db": "通信",
    "financial_asset_management": "金融",
    "healthcare_analytics_competition": "医疗",
}
_NL_DB_WORDS: dict[str, list[tuple[str, float]]] = {
    "telecom_operations_db": [
        ("套餐", 1.0), ("资费", 1.0), ("月租", 1.0), ("话费", 1.0), ("流量", 1.0),
        ("短信", 1.0), ("通话", 1.0), ("语音", 1.0), ("漫游", 1.0), ("话单", 1.0),
        ("账单", 1.0), ("缴费", 1.0), ("欠费", 1.0), ("停机", 1.0), ("销户", 1.0),
        ("入网", 1.0), ("开户", 1.0), ("号码", 0.7), ("手机号", 1.0), ("订购", 1.0),
        ("退订", 1.0), ("在网", 1.0), ("续费", 1.0), ("增值业务", 1.0), ("宽带", 1.0),
        ("5g", 1.0), ("投诉", 1.0), ("客服", 1.0), ("工单", 1.0), ("满意度", 1.0),
        ("营销活动", 1.0), ("活动", 0.4), ("基站", 1.0), ("网络", 0.5), ("充值", 1.0),
        ("客户", 0.4), ("用户", 0.4),
    ],
    "financial_asset_management": [
        ("理财", 1.0), ("基金", 1.0), ("股票", 0.9), ("债券", 0.9), ("净值", 1.0),
        ("持仓", 1.0), ("市值", 1.0), ("浮盈", 1.0), ("浮亏", 1.0), ("盈亏", 1.0),
        ("收益", 1.0), ("收益率", 1.0), ("亏损", 1.0), ("盈利", 1.0), ("赚", 0.7),
        ("赔", 0.7), ("申购", 1.0), ("赎回", 1.0), ("买入", 0.9), ("卖出", 0.9),
        ("分红", 1.0), ("派息", 1.0), ("转换", 0.8), ("交易", 0.7), ("成交", 1.0),
        ("佣金", 1.0), ("费率", 1.0), ("管理费", 1.0), ("业绩提成", 1.0),
        ("风险评级", 1.0), ("风险评估", 0.8), ("回撤", 1.0), ("夏普", 1.0),
        ("客户经理", 1.0), ("投资组合", 1.0), ("组合", 0.8), ("资产", 0.8),
        ("总资产", 1.0), ("产品", 0.4), ("在售", 1.0), ("股票型", 1.0),
        ("债券型", 1.0), ("货币型", 1.0), ("qdii", 1.0), ("另类", 1.0),
        ("业绩", 0.5), ("客户", 0.4),
    ],
    "healthcare_analytics_competition": [
        ("患者", 1.0), ("病人", 1.0), ("就诊", 1.0), ("挂号", 1.0), ("门诊", 1.0),
        ("急诊", 1.0), ("住院", 1.0), ("出院", 1.0), ("体检", 1.0), ("复诊", 1.0),
        ("主诉", 1.0), ("科室", 1.0), ("病区", 1.0), ("床位", 1.0), ("医生", 0.9),
        ("护士", 0.9), ("医护", 1.0), ("医嘱", 1.0), ("处方", 1.0), ("药品", 1.0),
        ("药费", 1.0), ("库存", 1.0), ("效期", 1.0), ("进销存", 0.8), ("医保", 1.0),
        ("报销", 1.0), ("自费", 1.0), ("自付", 1.0), ("结算", 1.0), ("费用", 0.5),
        ("诊疗", 1.0), ("治疗", 0.9), ("检查", 0.8), ("检验", 0.9), ("手术", 1.0),
        ("设备", 1.0), ("血压", 1.0), ("体温", 1.0), ("ct", 1.0), ("药", 0.7),
    ],
}
# 跨库/跨域泛词：单独命中不足以定库，仅作参考提示
_NL_WEAK_WORDS = {
    "客户", "用户", "产品", "账单", "费用", "交易", "业绩", "设备", "活动",
    "网络", "药", "多少", "怎么", "查", "看",
}
# 表 → 用户会挂在嘴边的对象词（表名与关联均已核验）
_NL_TABLE_HINTS: dict[str, dict[str, list[str]]] = {
    "telecom_operations_db": {
        "customers": ["用户", "客户", "停机", "欠费", "销户", "入网", "vip", "性别", "开户", "状态"],
        "products": ["套餐", "产品", "资费", "月租", "流量包", "语音包", "宽带", "5g", "在售", "价格", "基础套餐"],
        "subscriptions": ["订购", "开通", "办理", "退订", "在网", "合约", "生效", "号码", "新装"],
        "cdr_detail": ["话单", "通话", "语音", "时长", "短信", "流量", "漫游", "通话费", "详单"],
        "monthly_bills": ["账单", "话费", "缴费", "欠费", "月账单", "总金额", "未支付", "滞纳金"],
        "marketing_campaigns": ["营销活动", "活动", "预算", "roi", "转化率", "参与"],
        "service_records": ["投诉", "客服", "工单", "满意度", "服务", "热线", "报障"],
        "network_resources": ["基站", "网络", "设备", "容量", "利用率", "故障", "覆盖"],
    },
    "financial_asset_management": {
        "clients": ["客户", "开户", "等级", "风险类型", "总资产", "冻结", "销户", "客户档案"],
        "managers": ["客户经理", "理财师", "部门", "绩效", "管理资产", "经理"],
        "products": ["产品", "基金", "理财", "在售", "管理费", "业绩提成", "费率", "风险评级", "收益率", "股票型", "债券型", "货币型", "qdii"],
        "portfolios": ["组合", "投资组合", "市值", "当前价值", "累计投入", "盈亏", "亏", "赚", "终止"],
        "transactions": ["交易", "买入", "卖出", "申购", "赎回", "分红", "派息", "流水", "成交额", "佣金"],
        "holdings": ["持仓", "浮盈", "浮亏", "持仓量", "成本"],
        "risk_metrics": ["回撤", "夏普", "波动率", "风险指标", "var"],
        "counterparties": ["交易对手", "对手方", "信用评级"],
    },
    "healthcare_analytics_competition": {
        "patient_master_index": ["患者", "病人", "性别", "年龄", "医保余额", "vip", "姓名"],
        "medical_encounters": ["就诊", "门诊", "急诊", "住院", "出院", "体检", "复诊", "主诉", "诊断", "总费用", "单次费用", "接诊"],
        "medical_orders": ["医嘱", "处方", "药品", "药", "检查", "检验", "治疗", "手术", "护理", "开药"],
        "pharmacy_inventory": ["库存", "药品", "效期", "批号", "采购", "入库", "补货", "盘点", "警戒"],
        "medical_equipment_usage": ["设备", "ct", "使用时长", "设备费", "维护"],
        "medical_staff": ["医生", "护士", "医护", "绩效", "职称", "排班"],
        "departments_wards": ["科室", "病区", "床位", "临床", "医技"],
        "billing_transactions": ["结算", "收费", "账单", "缴费", "医保", "自费", "自付", "发票", "退款", "欠费", "支付方式", "医保报"],
    },
}
# 口语说法 → 正确字段/口径提示（列名均取自核验过的技能卡）
_NL_TERM_HINTS: list[tuple[list[str], str]] = [
    (["月租", "资费", "套餐价", "套餐费", "套餐价格"], "套餐/资费金额看 products.base_fee（单位元，比价限定 is_current=1）"),
    (["管理费", "年化管理", "费率", "业绩提成"], "金融费率：management_fee=年化管理费率（小数 0.01=1%）、performance_fee_rate=业绩提成；只对在售 is_active=1 比较"),
    (["风险评级", "风险等级", "r1", "r5", "低风险", "高风险"], "金融风险等级 products.risk_rating：1=最低、5=最高"),
    (["在售", "有效产品", "现网在售", "当前有效"], "产品目录口径：通信用 products.is_current=1，金融用 products.is_active=1"),
    (["赚", "盈利", "浮盈", "亏", "亏损", "浮亏", "赔"], "持仓浮动盈亏 holdings.unrealized_pnl；组合整体用 portfolios.current_value 对比 contribution_amount"),
    (["单次就诊", "就诊费用", "住院总费用", "住院花了", "一次就诊"], "就诊维度金额 medical_encounters.total_cost（不是结算表 net_amount）"),
    (["医保报", "医保付", "报销金额"], "结算流水看 billing_transactions.insurance_paid；就诊维度是 medical_encounters.insurance_payment"),
    (["自费", "自付", "个人掏"], "结算流水看 billing_transactions.patient_paid；就诊维度是 medical_encounters.patient_payment"),
    (["药还有", "库存", "快过期", "效期", "缺货"], "库存表 pharmacy_inventory 只有 drug_id 无药名，按药名问需先经 medical_orders 定位 drug_id"),
    (["用了多久", "设备时长", "用了多少小时"], "设备时长列是 duration_minutes（分钟），费用看 total_cost"),
    (["在网", "当前生效", "还订着", "没退订"], "订购“当前生效”= start_date<=CURDATE() AND end_date>=CURDATE() AND actual_end_date IS NULL"),
    (["这个月账单", "某月账单", "当月话费"], "通信账单账期列 monthly_bills.billing_month 是 DATE 值（YYYY-MM-01），用半开区间过滤"),
]
# 动作/结构提示词 → 写法要点
_NL_ACTION_HINTS: list[tuple[list[str], str]] = [
    (["最便宜", "最低", "价格最低", "月租最低", "费用最低", "最少", "最小"],
     "极值取小：ORDER BY 金额/费率列 ASC + LIMIT，先限定在售/当前口径（套餐 base_fee、费率 management_fee）"),
    (["最贵", "最高", "最大", "最多", "最长", "价格最高", "费用最高", "top", "前5", "前10", "排名"],
     "极值取大：ORDER BY 对应列 DESC + LIMIT，先限定在售/当前口径"),
    (["低于", "不超过", "不到", "小于", "在30元以下"], "数值上界过滤：列 < 阈值（注意单位：费率是小数、金额单位元）"),
    (["高于", "超过", "大于", "以上"], "数值下界过滤：列 > 阈值"),
    (["多少个", "几条", "几笔", "几人", "人数", "多少用户", "多少患者", "多少客户", "笔数", "次数"],
     "计数：COUNT(*)，按主体去重用 COUNT(DISTINCT 主键列)"),
    (["多少钱", "总金额", "合计", "总额", "一共", "总收入", "总费用", "净额"],
     "求和：SUM(金额列)（先分清口径表：就诊费 encounters.total_cost / 结算 billing_transactions.net_amount / 账单 monthly_bills.total_amount）"),
    (["平均", "均值", "人均", "平均水平"], "求均值：AVG(列)；先留意 NULL/负值（如金融 clients.total_assets）"),
    (["占比", "分布", "比例", "构成", "分别多少"], "分组计数算占比：GROUP BY 维度列 + COUNT(*)"),
    (["这个月", "本月", "上月", "上个月", "近30天", "近一月", "近半年", "近一年", "去年", "今年", "2023", "2024", "2025", "季度"],
     "时间词→先确认时间列类型再过滤：医疗 DATETIME 直接比较、金融 VARCHAR ISO / 通信 VARCHAR DATE 用字符串半开区间，不要对字符串列 YEAR()/DATE_FORMAT()"),
    (["按", "每个", "各", "分组", "分别"], "按维度分组聚合：GROUP BY 维度列后做 SUM/COUNT/AVG"),
]


@tool
def analyze_query(question: str) -> str:
    """对用户的中文问句做“关键词抓取 + 库/表/术语定位”（纯本地规则，不查库、不耗 LLM）。

    当问句比较口语化、或拿不准属于哪个库/哪张表、或不确定口语词对应哪个字段时，
    先调用本工具抓取关键字与关键提示词，返回：命中的领域词、判定库（含置信）、
    疑似表、口语→字段口径对照与动作/时间写法提示；再据此用 get_db_skill /
    get_table_schema 核实后写 SQL。参数 question 传入用户问句原文。"""
    q = (question or "").strip().lower()
    if not q:
        return "空问题：请传入用户问句原文。"
    lines: list[str] = []

    # ① 库级命中：命中词的加权总分与强词数量
    db_score: dict[str, float] = {}
    db_strong: dict[str, list[str]] = {}
    db_words_hit: dict[str, list[str]] = {}
    for db, words in _NL_DB_WORDS.items():
        total, strong, hits = 0.0, [], []
        for word, weight in words:
            if word in q:
                hits.append(word)
                total += weight
                if weight >= 0.9:
                    strong.append(word)
        if hits:
            db_score[db] = total
            db_strong[db] = strong
            db_words_hit[db] = hits

    weak_only = True
    if db_score:
        for db in db_score:
            if db_strong.get(db):
                weak_only = False
                break

    if not db_score or weak_only:
        weak_hits = sorted({w for db in db_score for w in db_words_hit[db] if w in _NL_WEAK_WORDS})
        lines.append(
            "[判库] 低置信：只命中跨域泛词" + ("（" + "、".join(weak_hits) + "）" if weak_hits else "")
            + "，三个库都可能存在。建议先调用 get_db_skill() 对比三张技能卡，或 list_database_tables 看表，再向用户确认业务范围（通信/金融/医疗）。"
        )
        candidates = []
        for db in sorted(db_score, key=lambda d: db_score[d], reverse=True):
            lab = _NL_DB_LABEL[db]
            w = "、".join(db_words_hit[db])
            candidates.append(f"{lab}({db})：命中「{w}」")
        lines.append("[候选库] " + "；".join(candidates))
    else:
        # 强命中库按分排序，取前两名
        order = sorted(db_score, key=lambda d: db_score[d], reverse=True)
        primary = order[0]
        lines.append(
            f"[判库] {_NL_DB_LABEL[primary]}({primary})，置信高；"
            f"命中领域词：{'、'.join(db_strong[primary][:8]) or '、'.join(db_words_hit[primary][:8])}"
        )
        if len(order) >= 2 and db_strong.get(order[1]):
            sec = order[1]
            lines.append(
                f"[注意] 同时命中 {_NL_DB_LABEL[sec]}({sec})：{('、'.join(db_strong[sec][:6]))}，"
                "若问句指向它请按该库处理"
            )

        # ② 表级线索：按命中词数量推荐主判库的表
        if primary in _NL_TABLE_HINTS:
            scored = []
            for table, hint_words in _NL_TABLE_HINTS[primary].items():
                matched = [w for w in hint_words if w in q]
                if matched:
                    scored.append((len(matched), table, matched))
            scored.sort(key=lambda item: item[0], reverse=True)
            if scored:
                tops = scored[:3]
                lines.append(
                    "[疑似表] " + "；".join(
                        f"{primary}.{t}（命中：{'、'.join(m[:5])}）" for _, t, m in tops
                    )
                )

    # ③ 术语对照：口语说法 → 正确字段/口径
    term_hits = [note for words, note in _NL_TERM_HINTS if any(w in q for w in words)]
    if term_hits:
        lines.append("[术语对照] " + "；".join(term_hits))

    # ④ 动作/时间提示词 → 写法要点
    act_hits = [note for words, note in _NL_ACTION_HINTS if any(w in q for w in words)]
    if act_hits:
        lines.append("[写法提示] " + "；".join(act_hits))

    lines.append("以上为规则抓词定位建议，表与列一律以 get_table_schema 返回的真实结构为准。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# sklearn 机器学习预测（三个业务库的月度指标 → 未来趋势 + Markdown 报告）
# --------------------------------------------------------------------------- #
@tool
def list_forecast_metrics() -> str:
    """列出可用 sklearn 预测的全部业务指标（金融/医疗/通信三个库），含指标 key、所属库、
    聚合口径与业务含义。当用户想做预测 / 问未来趋势，而你不确定该用哪个指标时先调用它。"""
    try:
        return ml_forecast.list_metrics_text()
    except Exception as exc:
        return f"获取预测指标目录失败：{exc}"


@tool
def forecast_metric(metric: str, horizon: int = 6) -> str:
    """用 sklearn 机器学习模型训练历史数据并预测未来 N 个月的业务指标，生成 Markdown 预测报告。

    参数 metric 必须是 list_forecast_metrics 给出的指标 key（如 healthcare_revenue、
    finance_trade_amount、telecom_bill_amount，下划线前缀即库名缩写）；horizon 为预测月数，
    默认 6，最大 24。
    该工具会自动：① 查询对应库历史明细并按自然月聚合；② 在 LinearRegression / Ridge /
    RandomForest / GradientBoosting / SVR 中用前向验证选出验证期 RMSE 最优的模型并训练；
    ③ 递归滚动预测未来 N 个月，返回各月预测值、趋势结论与 reports/ 下的 .md 报告路径。

    当用户要求“预测 / 未来某个月 / 走向 / 趋势判断 / 生成预测报告 / 用机器学习模型看……”时
    调用本工具。用返回的预测数字和趋势直接回答即可。"""
    try:
        out = ml_forecast.run_forecast(metric=metric, db=None, horizon=horizon)
    except Exception as exc:
        return f"预测失败：{exc}（不确定指标 key 时，先调用 list_forecast_metrics 查看可选指标）"
    # 数据来源：预测不是凭空算出来的，把“哪个库哪张表哪列 + 预测月数 + 报告路径”登记清楚
    conf = ml_forecast.METRIC_CATALOG.get(metric) or {}
    db_name = conf.get("db") or ""
    bits = [conf.get("name") or metric, f"预测未来 {horizon} 个月"]
    if out.get("report_path"):
        bits.append(f"报告 {out['report_path']}")
    record_source(
        "forecast", metric,
        label="机器学习预测 · " + (_DB_SHORT.get(db_name) or "业务库"),
        tables=[conf.get("table")] if conf.get("table") else [],
        detail=" · ".join(str(b) for b in bits if b),
    )
    parts = [out["summary"]]
    if out.get("report_path"):
        parts.append(f"\nMarkdown 预测报告已生成：{out['report_path']}")
    return "\n".join(parts)


def database_status() -> dict:
    """探测三个业务库是否连通（供 /api/health 展示，不含任何数据）。"""
    try:
        conn = db_connect()
        try:
            with conn.cursor() as cur:
                databases = []
                for db in DB_CATALOG:
                    cur.execute(f"SHOW TABLES FROM `{db}`")
                    databases.append(f"{db}（{len(cur.fetchall())} 张表）")
        finally:
            conn.close()
        return {"ok": True, "databases": databases}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
# ---- 数据洞察类工具共享的小部件：库名别名解析 / 逗号分隔列名 ---- #
_DB_ALIAS = {
    "finance": "financial_asset_management", "financial": "financial_asset_management",
    "金融": "financial_asset_management", "financial_asset_management": "financial_asset_management",
    "healthcare": "healthcare_analytics_competition", "medical": "healthcare_analytics_competition",
    "医疗": "healthcare_analytics_competition",
    "healthcare_analytics_competition": "healthcare_analytics_competition",
    "telecom": "telecom_operations_db", "通信": "telecom_operations_db",
    "telecom_operations_db": "telecom_operations_db",
}


def _resolve_db_name(database: str) -> str:
    """把 finance / 医疗 这类简称换成真实库名；给不出就原样返回（由下游报错）。"""
    return _DB_ALIAS.get(str(database or "").strip().lower()) or str(database or "").strip()


def _split_cols(text: str) -> list[str]:
    """把 "a, b, c" / "a，b" / "a b" 拆成列名列表。"""
    parts = re.split(r"[,，;；\s]+", str(text or "").strip())
    return [p for p in parts if p]


def _last_result_rows(limit: int = 2000) -> tuple[list[str], list[dict]]:
    """把最近一次查询结果转成 [{列名: 值}]，供 Python 沙箱直接算。

    值会被规整成「沙箱友好的类型」：Decimal → float、日期 → 字符串、其余保持原样。
    """
    cols = list(_LAST_QUERY.get("headers") or [])
    raw = list(_LAST_QUERY.get("rows") or [])[:limit]
    rows: list[dict] = []
    for row in raw:
        item: dict = {}
        for key, value in zip(cols, list(row)):
            try:
                if hasattr(value, "as_tuple"):          # Decimal
                    item[key] = float(value)
                elif isinstance(value, (int, float, bool)) or value is None:
                    item[key] = value
                elif hasattr(value, "isoformat"):       # date / datetime
                    item[key] = value.isoformat()
                else:
                    item[key] = str(value)
            except Exception:
                item[key] = str(value)
        rows.append(item)
    return cols, rows


@tool
def run_python(code: str) -> str:
    """用 Python 对**最近一次查询结果**做二次计算（同比环比、移动平均、分位数、线性回归、
    多结果集四则运算、字符串清洗等 SQL 不好写或写起来很绕的活）。

    调用方式：先用 execute_sql / query_tables 查出数据，再用本工具算，
    查询结果会自动注入为变量 rows（列表，每元素是一行的字典）与 cols（列名列表）。

    可用：四则与比较运算、列表/字典推导、sum/len/sorted/round/min/max/abs/enumerate/zip 等内置函数，
    以及 math（sqrt/log 等）、statistics（mean/median/stdev 等）、numpy（写作 np）。
    禁止：import、文件读写、while 循环（请用 for + range）；超过 50 万次迭代会自动中止。

    取值方式二选一：① 把结果赋给 result 变量；② 最后一行为裸表达式（会自动取其值）。
    print() 的输出也会被捕获返回。

    示例：
      run_python("sum(r['amount'] for r in rows)")                       # 汇总
      run_python("result = sorted(rows, key=lambda r: -r['amount'])[:5]") # Top5
      run_python("import statistics" ...)                                # 错误：不允许 import
    """
    cols, rows = _last_result_rows()
    if not rows:
        return "（还没有可计算的数据：请先执行 execute_sql 或 query_tables 查询。）"
    # 数据进沙箱**之前**先按列名脱敏：模型拿到的数据本身就是干净的，
    # 无论它怎么写代码（sorted / filter / 原样输出）都不可能把个人信息吐出来。
    # （execute_sql 已脱过一次，mask_rows 幂等，重复处理安全）
    try:
        matrix = [[row.get(c) for c in cols] for row in rows]
        cols, masked, _masked_cols = sanitize.mask_rows(list(cols), matrix)
        rows = [dict(zip(cols, line)) for line in masked]
    except Exception:
        pass
    outcome = pysandbox.run(code, {"rows": rows, "cols": cols})
    if not outcome.get("ok"):
        return f"计算失败：{outcome.get('error') or '未知错误'}\n可参考：变量名用 rows（行字典列表）/ cols（列名）。"
    lines = [f"【数据】来自最近一次查询：{len(rows)} 行，列：{'、'.join(cols[:12])}"]
    if outcome.get("stdout"):
        lines.append(f"【print 输出】\n{outcome['stdout']}")
    lines.append(f"【计算结果】{outcome.get('result_text')}")
    if len(rows) >= 2000:
        lines.append("提示：只注入了前 2000 行，如需全量请先 SQL 聚合。")
    # 结果里可能整行带出姓名/电话/证件号（比如 sorted(rows,…)），与 execute_sql 同一口径脱敏
    return sanitize.mask_text("\n".join(lines))


@tool
def analyze_data(database: str, table: str, columns: str = "", where: str = "",
                 sample_limit: int = 5000) -> str:
    """对某个业务库的表做**统计分析**（中级数据分析）：自动挑选数值列，给出完整统计画像
    （非空数、缺失率、均值、中位、四分位、标准差、变异系数、偏度），并计算列两两之间的
    皮尔逊 / 斯皮尔曼相关系数，挑出最强相关的组合加以解读。适合先于 SQL 手工聚合，
    用来摸清一张表的数据分布与可用性。

    参数：database 用 finance / medical / telecom（或完整库名）；table 表名；
    columns 可选，指定要分析的列名，逗号分隔，留空表示自动选全部数值列；
    where 可选过滤条件（如 "PaymentStatus='PAID'"）；sample_limit 抽样行数上限，默认 5000。
    """
    db = _resolve_db_name(database)
    try:
        cols = _split_cols(columns) or None
        limit = max(100, min(int(sample_limit or 5000), ml_insight.MAX_SAMPLE))
        headers, rows = ml_insight.fetch_rows(db, table, cols, where=where, limit=limit)
        picked, matrix = ml_insight._numeric_matrix(rows, headers, cols)
        if not picked:
            return f"（表 {db}.{table} 没有可用于统计的数值列；先用 get_table_schema 看一下列结构。）"
        profile = ml_insight.numeric_profile(matrix, picked)
        skipped = list(getattr(ml_insight._numeric_matrix, "last_skipped", []) or [])
        lines = [
            f"数据来源：{db}.{table}（{'有条件过滤' if where else '全表'}，抽样 {len(rows)} 行）",
            "",
            ml_insight.render_profile(profile),
            "",
            ml_insight.render_corr(ml_insight.correlation_matrix(matrix, picked)),
        ]
        if skipped:                                  # 说明哪些列被排除，避免模型以为数据丢了
            lines += ["", "未参与统计的列：" + "、".join(
                f"{item['列']}（{item['原因']}）" for item in skipped[:8])]
        return sanitize.mask_text("\n".join(lines))
    except Exception as exc:
        return f"统计分析失败：{exc}"


@tool
def detect_data_anomalies(database: str, table: str, value_col: str, label_col: str = "",
                          where: str = "") -> str:
    """**自动建模之一：异常检测**（高级数据分析）。对指定数值列用三种口径一起投票找出离群点：
    z-score（偏离 3σ 以上）、箱线图（超出 1.5 倍四分位距）、孤立森林 IsolationForest。
    至少两种口径同时命中才判为异常，避免把「重尾分布里的正常大客户」误判成异常。
    适合回答「哪些月/哪些客户/哪些订单不正常」这类问题。

    参数：database 同 analyze_data；table 表名；value_col 要检测的数值列（如 金额、用量）；
    label_col 可选，用来标记异常行的列（如 月份、客户名、订单号），便于读懂是谁异常；
    where 可选过滤条件。
    """
    db = _resolve_db_name(database)
    try:
        cols = [value_col] + ([label_col] if label_col else [])
        limit = max(200, min(int(ml_insight.MAX_SAMPLE), 20000))
        headers, rows = ml_insight.fetch_rows(db, table, cols, where=where, limit=limit)
        if value_col not in headers:
            return f"（表里没有列 {value_col}；可用列：{'、'.join(headers[:15])}）"
        vi, li = headers.index(value_col), headers.index(label_col) if label_col in headers else -1
        values = ml_insight._to_float_list([r[vi] if vi < len(r) else None for r in rows])
        labels: list[str] = []
        if li >= 0:
            raw_labels = [str(r[li]) for r in rows]
            # 标签列按**真实列名**走一遍脱敏：像 patient_name 这种列会被判成姓名，
            # 而纯文本正则认不出没有称谓跟着的裸人名（"李玉梅" vs "患者李玉梅"）
            _, masked_labels, _hits = sanitize.mask_rows([label_col], [[v] for v in raw_labels])
            labels = [str(line[0]) for line in masked_labels]
        result = ml_insight.detect_outliers(values, labels)
        head = f"数据来源：{db}.{table}（{len(rows)} 行，检测列 {value_col}）"
        # label_col 常常是客户名 / 订单号：异常点会直接把这些值带出来，必须先脱敏
        return sanitize.mask_text(head + "\n\n" + ml_insight.render_outliers(result, value_col))
    except Exception as exc:
        return f"异常检测失败：{exc}"


@tool
def cluster_data(database: str, table: str, columns: str, max_k: int = 4, where: str = "") -> str:
    """**自动建模之二：聚类挖掘**（高级数据分析）。按给定数值列对行做客户/对象分群：
    自动标准化后在 k=2..max_k 里用轮廓系数选出最优簇数（KMeans），给出每个簇的规模、
    占比、以及**哪些特征相对整体显著偏高/偏低**，并据此给簇起一个像「金额偏高、频次偏低」的画像名。
    适合回答「客户能分成几类、每类什么特点」这类没有现成标签的问题。

    参数：database 同 analyze_data；table 表名；columns 参与分群的数值列，逗号分隔（建议 2~5 个）；
    max_k 最大簇数，默认 4；where 可选过滤条件。
    """
    db = _resolve_db_name(database)
    try:
        cols = _split_cols(columns)
        if len(cols) < 1:
            return "（请至少给出 1 个用于分群的数值列。）"
        limit = max(200, min(int(ml_insight.MAX_SAMPLE), 20000))
        headers, rows = ml_insight.fetch_rows(db, table, cols, where=where, limit=limit)
        picked, matrix = ml_insight._numeric_matrix(rows, headers, cols)
        if not picked:
            return f"（这些列没有可用的数值数据：{columns}）"
        k = max(2, min(int(max_k or 4), 6))
        result = ml_insight.cluster_profile(matrix, picked, max_k=k)
        head = f"数据来源：{db}.{table}（{len(rows)} 行，分群依据：{'、'.join(picked)}）"
        tail = ""
        skipped = list(getattr(ml_insight._numeric_matrix, "last_skipped", []) or [])
        if skipped:
            tail = "\n\n未参与分群的列：" + "、".join(
                f"{item['列']}（{item['原因']}）" for item in skipped[:8])
        return sanitize.mask_text(head + "\n\n" + ml_insight.render_clusters(result) + tail)
    except Exception as exc:
        return f"聚类分析失败：{exc}"


@tool
def query_table_python(code: str, table: str = "", question: str = "") -> str:
    """用 **Python（pandas）** 查询表格数据——SQL 不好写时用这个（分组透视、多层索引、
    字符串清洗、时间重采样、多表合并、占比与同比环比等）。

    数据已注入为变量 **df**（pandas DataFrame），另可直接用 **pd**（pandas）与 **np**（numpy）。
    取值方式：① 把结果赋给 result 变量；② 最后一行为裸表达式（自动取其值）。print() 也会返回。

    参数：code 要执行的 Python；table 表名或文件名关键字（留空则取最近一次 find_table 的表）；
    question 把用户问题原文带过来（**会连同这段代码一起记进记忆**，下次问相似问题就能复用）。

    示例：
      query_table_python("df.groupby('学院').size().sort_values(ascending=False)", table="test")
      query_table_python("result = df[df['困难等级']=='特别困难'].shape[0]")
      query_table_python("df.pivot_table(index='学院', columns='困难等级', values='序号', aggfunc='count')")

    规则：不允许 import / open / while；列名照抄 describe_table 返回的列名（中文列名可直接用）。
    """
    try:
        from services import uploads
        frame, used = uploads.load_dataframe(table or _LAST_TABLE.get("name", ""))
    except Exception as exc:
        return (f"取表失败：{exc}\n先用 find_table 召回候选表（它会告诉你表名与列名），"
                "再调用本工具。")
    _LAST_TABLE["name"] = used
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        return f"环境缺少 pandas/numpy：{exc}"
    outcome = pysandbox.run(code, {"df": frame, "pd": pd, "np": np})
    if not outcome.get("ok"):
        return f"执行失败：{outcome.get('error')}\n提示：数据在 df 里，列名见 describe_table；不能有 import / while。"

    result = outcome.get("result")
    if hasattr(result, "to_string"):                       # DataFrame / Series：完整表格输出
        shown = result.to_string(max_rows=60, max_cols=30)
    elif isinstance(result, (list, dict, tuple, set)):
        shown = json.dumps(result, ensure_ascii=False, default=str)[:2000]
    else:
        shown = str(result)
    head = f"【数据表】{used}（{len(frame)} 行 × {len(frame.columns)} 列）"
    if getattr(frame, "columns", None) is not None and len(frame.columns):
        head += "\n【列名】" + "、".join(str(c) for c in list(frame.columns)[:20])
    text = "\n".join([head, "【计算结果】" + shown])
    if outcome.get("stdout"):
        text += "\n【print 输出】" + outcome["stdout"]

    # 自动学习：把「问题 → 代码」记下来，下次遇到相似问题直接复用
    if question or code:
        try:
            from services import table_memory
            table_memory.remember_query(question or "(未注明问题)", code, table=used)
        except Exception:
            pass
    return sanitize.mask_text(text)


@tool
def calculator(expression: str) -> str:
    """安全地计算数学表达式，支持 sqrt、pow、sin、log、pi 等常见数学函数。"""
    allowed_names = {
        name: getattr(math, name)
        for name in [
            "sqrt", "pow", "sin", "cos", "tan", "asin", "acos", "atan",
            "log", "log10", "exp", "pi", "e", "ceil", "floor", "fabs",
            "factorial",
        ]
    }

    def _eval_node(node: ast.AST):
        """AST 白名单求值：仅允许数字常量 / 四则、幂、取模 / 一元正负号 /
        白名单数学函数调用。杜绝属性链（().__class__.__bases__…）逃逸。"""
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError("仅支持数字常量")
        if isinstance(node, ast.BinOp):
            left, right = _eval_node(node.left), _eval_node(node.right)
            op = type(node.op)
            if op is ast.Add:
                return left + right
            if op is ast.Sub:
                return left - right
            if op is ast.Mult:
                return left * right
            if op is ast.Div:
                return left / right
            if op is ast.Pow:
                return left ** right
            if op is ast.Mod:
                return left % right
            raise ValueError(f"不支持的运算符：{op.__name__}")
        if isinstance(node, ast.UnaryOp):
            value = _eval_node(node.operand)
            if type(node.op) is ast.USub:
                return -value
            if type(node.op) is ast.UAdd:
                return +value
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_names:
                raise ValueError("只允许调用白名单内的数学函数")
            if node.keywords:
                raise ValueError("不支持关键字参数")
            args = [_eval_node(a) for a in node.args]
            return allowed_names[node.func.id](*args)
        if isinstance(node, ast.Name):
            if node.id in allowed_names:
                return allowed_names[node.id]
            raise ValueError(f"不支持的变量：{node.id}")
        raise ValueError(f"表达式包含不支持的语法：{type(node).__name__}")

    expr = (expression or "").strip()
    if not expr:
        return "计算失败：表达式为空"
    if len(expr) > 200:
        return "计算失败：表达式过长（上限 200 字符）"
    try:
        tree = ast.parse(expr, mode="eval")
        return f"{expression} = {_eval_node(tree)}"
    except Exception as exc:
        return f"计算失败：{exc}"


@tool
def get_current_time() -> str:
    """获取当前日期和时间，格式为 YYYY-MM-DD HH:MM:SS。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def word_count(text: str) -> str:
    """统计文本中的中文字符数和按空白分隔的文本片段数。"""
    chinese_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return f"中文字符 {chinese_chars} 个；非空文本片段 {len(text.split())} 个。"


_BASE_TOOLS = [calculator, get_current_time, word_count]


@tool
def search_knowledge(query: str) -> str:
    """检索本地知识库（knowledge/ 目录下的人工整理资料），返回相关原文片段、来源文件名与段落号。
    检索为“智能检索”：对全部可用检索引擎（关键词 [+ 语义向量，配置了 EMBEDDING_* 时]）做
    多路召回并 RRF 融合重排（可用 RAG_RERANK=1 再加一轮 LLM 相关度重排），只取最相关的若干片段。
    仅当问题涉及产品说明、使用手册、FAQ、内部政策等文档化资料时才调用；
    涉及数据库取数/统计请改用 get_table_schema + execute_sql 直查真实库，不要用本工具拼 SQL。"""
    return smart_search(query)


# --------------------------------------------------------------------------- #
# 跨会话存储（LangGraph Store / 长期记忆）
# --------------------------------------------------------------------------- #
# 和 Checkpointer 的区别：
#   - Checkpointer：按 thread_id 隔离“单场对话”的消息历史（会话之间不可见）；
#   - Store：全局共享的 Key-Value 持久化（langgraph.store 的 BaseStore 语义），
#     任意会话都能读写同一份长期记忆，服务重启后仍在。
# 这里用同步 SqliteStore 落盘到 data/memory.sqlite3；环境缺依赖时退回内存版。
MEMORY_DB = DATA_DIR / "memory.sqlite3"
_STORE_CACHE: dict = {"store": None, "backend": None}
_store_lock = threading.RLock()


def get_store():
    """懒构建全局共享的 Store，返回 (store, backend_name)。"""
    with _store_lock:
        if _STORE_CACHE["store"] is None:
            try:
                from langgraph.store.sqlite import SqliteStore
            except ImportError:
                from langgraph.store.memory import InMemoryStore

                _STORE_CACHE.update({"store": InMemoryStore(), "backend": "memory"})
                return _STORE_CACHE["store"], _STORE_CACHE["backend"]
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            # langgraph 的 SqliteStore 要求 autocommit 模式（它内部自己发 BEGIN），
            # 所以必须显式 isolation_level=None，否则会报 “cannot start a transaction…”
            conn = sqlite3.connect(
                str(MEMORY_DB), check_same_thread=False, isolation_level=None
            )
            _STORE_CACHE.update({"store": SqliteStore(conn), "backend": "sqlite"})
        return _STORE_CACHE["store"], _STORE_CACHE["backend"]


# 长期记忆的结构化字段：内容 + 类型 + 标签 + 重要度 + 使用次数。
# 旧数据（只有 content / created_at）也能被下面的读取函数兼容。
MEMORY_NS = ("long_term",)
MEMORY_KINDS = ("fact", "preference", "task", "other")
MEMORY_SCAN_LIMIT = 500


def _norm_memory_text(text: str) -> str:
    """归一化记忆文本，用于查重（忽略空白与常见标点差异）。"""
    return re.sub(r"[\s，。；、,.;!！?？]+", "", (text or "").strip()).lower()


def _memory_items(limit: int = MEMORY_SCAN_LIMIT) -> list[dict]:
    """读出长期记忆的结构化列表（含 key），按更新时间倒序。"""
    store, _ = get_store()
    items: list[dict] = []
    for item in store.search(MEMORY_NS, limit=limit):
        value = dict(item.value or {})
        items.append({
            "key": item.key,
            "content": value.get("content", ""),
            "kind": value.get("kind", "fact"),
            "tags": value.get("tags") or [],
            "importance": int(value.get("importance", 1) or 1),
            "use_count": int(value.get("use_count", 0) or 0),
            "created_at": value.get("created_at", ""),
            "updated_at": value.get("updated_at") or value.get("created_at", ""),
            "last_used_at": value.get("last_used_at", ""),
        })
    items.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return items


def _memory_score(query: str, item: dict) -> float:
    """长期记忆的相关度打分：查询词与记忆内容的词重叠（中文按「字 + 双字词」，复用 rag 分词）。

    查询为空时退化为「重要度」排序，保证 recall() 不带参数也能给出最有价值的记忆。
    """
    query_tokens = {t for t in rag_tokenize(query or "") if t.strip()}
    if not query_tokens:
        return float(item.get("importance", 1))
    blob = " ".join([
        str(item.get("content", "")),
        " ".join(item.get("tags") or []),
        str(item.get("kind", "")),
    ]).lower()
    doc_tokens = set(rag_tokenize(blob))
    if not doc_tokens:
        return 0.0
    hit = sum(1 for token in query_tokens if token in doc_tokens)
    if not hit:
        return 0.0
    # 命中覆盖率为主，重要度 / 使用次数作小幅加权（避免"越用越偏"）
    return (hit / len(query_tokens)) * 10 + min(item.get("importance", 1), 5) * 0.2 \
        + min(item.get("use_count", 0), 5) * 0.05


def list_memories(limit: int = 200) -> list[dict]:
    """列出 Store 里的全部跨会话记忆（供 HTTP 接口 / 界面展示）。"""
    return _memory_items(limit=limit)


def search_memories(query: str = "", limit: int = 8) -> list[dict]:
    """按相关度检索长期记忆；query 为空时返回最近更新的若干条。"""
    items = _memory_items()
    if not (query or "").strip():
        return items[:limit]
    scored = [(item, _memory_score(query, item)) for item in items]
    scored = [(item, score) for item, score in scored if score > 0]
    scored.sort(key=lambda pair: (pair[1], pair[0].get("updated_at", "")), reverse=True)
    result = []
    for item, score in scored[:limit]:
        row = dict(item)
        row["score"] = round(score, 3)
        result.append(row)
    return result


def _touch_memory(item: dict) -> None:
    """标记某条记忆刚被使用（use_count + 最近使用时间），失败不影响主流程。"""
    try:
        store, _ = get_store()
        store.put(MEMORY_NS, item["key"], {
            "content": item.get("content", ""),
            "kind": item.get("kind", "fact"),
            "tags": item.get("tags") or [],
            "importance": item.get("importance", 1),
            "use_count": int(item.get("use_count", 0)) + 1,
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "last_used_at": _now(),
        })
    except Exception:
        pass


def delete_memory(key: str) -> bool:
    """按 key 删除一条跨会话记忆。"""
    store, _ = get_store()
    store.delete(MEMORY_NS, key)
    return True


def store_summary() -> dict:
    """Store 概况（条数 + 类型分布），用于 /api/health。"""
    try:
        _, backend = get_store()
        items = _memory_items()
        kinds: dict[str, int] = {}
        for item in items:
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        return {"backend": backend, "memories": len(items), "kinds": kinds}
    except Exception:
        return {"backend": "unavailable", "memories": 0, "kinds": {}}


def tables_summary() -> dict:
    """非结构化表格库概况（数据集 / 表数 / 行数），供 /api/health。索引未建时不触发构建。"""
    if not TABLE_ENABLED:
        return {"ok": False, "error": "未启用（缺少 非结构化数据/ 目录或数据文件）"}
    try:
        info = tables.stats()
        if not info.get("ok"):
            return {"ok": False, "error": "索引未建立（首次使用或运行 python tables.py --build）"}
        return {
            "ok": True,
            "tables": info.get("tables"),
            "rows": info.get("rows"),
            "db_mb": round((info.get("db_bytes") or 0) / 1024 / 1024, 1),
            "built_at": info.get("built_at"),
            "datasets": {key: row.get("tables") for key, row in (info.get("datasets") or {}).items()},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def memory_summary() -> dict:
    """记忆概况（三层记忆各自的载体与规模），用于 /api/health。"""
    enabled, after, keep = _digest_config()
    try:
        store, _ = get_store()
        digests = len(store.search(DIGEST_NS, limit=500))
    except Exception:
        digests = 0
    return {
        "layers": {
            "checkpointer": "会话内消息历史（按 thread_id 隔离，完整保留）",
            "store": "跨会话长期记忆（remember / recall / forget）",
            "digest": "长会话滚动摘要（自动压缩早期对话）",
        },
        "compact": {"enabled": enabled, "after": after, "keep": keep, "digests": digests},
    }


@tool
def remember(content: str, kind: str = "fact", tags: str = "") -> str:
    """把一条重要信息写入“跨会话长期记忆”（所有会话共享、进程重启后仍在）。
    只有当用户明确要求“记住 / 长期记住 / 别忘了 / 帮我记一下”时才调用；
    把需要记住的事实整理成一句完整、自洽的话传入 content。
    kind：记忆类型，fact=事实（默认）/ preference=偏好 / task=待办 / other=其它；
    tags：可选标签，逗号分隔（如“客户,偏好”），之后 recall 会按相关度命中。
    内容完全相同的记忆不会产生副本，只会刷新时间并提升重要度。"""
    text = " ".join((content or "").split())
    if not text:
        return "（要记住的内容为空，未写入。）"
    store, backend = get_store()
    kind = (kind or "fact").strip().lower()
    if kind not in MEMORY_KINDS:
        kind = "other"
    tag_list = [t.strip() for t in re.split(r"[,，;；\s]+", tags or "") if t.strip()][:8]
    now = _now()
    normalized = _norm_memory_text(text)
    for item in _memory_items():
        if _norm_memory_text(item["content"]) == normalized:
            store.put(MEMORY_NS, item["key"], {
                "content": item["content"],
                "kind": item.get("kind") or kind,
                "tags": sorted(set((item.get("tags") or []) + tag_list)),
                "importance": min(int(item.get("importance", 1)) + 1, 5),
                "use_count": item.get("use_count", 0),
                "created_at": item.get("created_at") or now,
                "updated_at": now,
                "last_used_at": item.get("last_used_at", ""),
            })
            return f"这条信息之前已经记住过，已刷新时间并提高重要度（{backend} Store）。"
    store.put(MEMORY_NS, uuid.uuid4().hex, {
        "content": text, "kind": kind, "tags": tag_list, "importance": 1,
        "use_count": 0, "created_at": now, "updated_at": now, "last_used_at": "",
    })
    total = len(_memory_items())
    return f"已存入跨会话长期记忆（{backend} Store，类型 {kind}），当前共 {total} 条。"


@tool
def recall(query: str = "") -> str:
    """查询跨会话长期记忆：其它会话里用户明确要求记住的个人信息 / 偏好 / 事实 / 待办。
    当问题涉及“我叫什么、我喜欢什么、我之前跟你说过、我在跟哪个项目”等跨会话信息时，
    先调用它拿到已有记忆再回答，不要凭空编造。
    query 传当前问题的关键词（如“姓名 偏好”“报销 标准”），会按相关度返回最匹配的若干条；
    留空则返回最近记住的若干条（条数较多，建议带上关键词再用）。"""
    items = search_memories(query or "", limit=8)
    if not items:
        return "（暂无长期记忆）" if not (query or "").strip() else "（没有找到相关长期记忆）"
    lines = []
    for item in items:
        tags = "、".join(item.get("tags") or []) or "无标签"
        head = f"- [{item.get('kind', 'fact')}｜标签：{tags}"
        if item.get("score") is not None:
            head += f"｜相关度 {item['score']}"
        head += f"｜记于 {item.get('created_at', '?')}]"
        lines.append(f"{head} {item.get('content', '')}")
        _touch_memory(item)
    return "\n".join(lines)


@tool
def forget(target: str) -> str:
    """删除跨会话长期记忆：用户明确要求“忘掉 / 删除记忆 / 别再记着”某条信息时调用。
    target 可以是记忆内容的片段（如“我的手机号”），也可以是记忆 key 的前几位。"""
    target = (target or "").strip()
    if not target:
        return "（请说明要忘记的内容。）"
    store, _ = get_store()
    normalized = _norm_memory_text(target)
    removed: list[str] = []
    for item in _memory_items():
        by_key = item["key"].startswith(target)
        by_text = bool(normalized) and normalized in _norm_memory_text(item["content"])
        if by_key or by_text:
            store.delete(MEMORY_NS, item["key"])
            removed.append(item["content"])
    if not removed:
        return f"（没有找到与“{target}”相关的记忆。）"
    return f"已删除 {len(removed)} 条记忆：" + "；".join(r[:60] for r in removed)


# --------------------------------------------------------------------------- #
# 规划（Planning）：先拆解 → 按步执行 → 自检闭环
# --------------------------------------------------------------------------- #
# 计划保存在内存注册表里（按 thread_id 索引），并同步落盘到会话元数据
# （data/conversations.json），所以重开页面还能看到上次的计划与进度。
# 工具是普通函数、拿不到 thread_id，这里用 ContextVar 由 ChatService 在每轮问答
# 开始时注入「当前会话」，remember / plan_task / update_plan 等工具据此定位上下文。
_PLAN_THREAD: contextvars.ContextVar[str] = contextvars.ContextVar("wh_plan_thread", default="default")
_PLANS: dict[str, planning.Plan] = {}
_PLANS_LOCK = threading.RLock()


def current_thread_id() -> str:
    """当前正在执行的会话 thread_id（由 ChatService 注入）。"""
    return _PLAN_THREAD.get()


def set_current_thread(thread_id: str | None) -> None:
    """标记当前正在处理哪个会话（供规划 / 记忆类工具使用）。"""
    _PLAN_THREAD.set(thread_id or "default")


def get_active_plan(thread_id: str | None = None) -> planning.Plan | None:
    """取某会话当前的执行计划；没有计划返回 None。"""
    with _PLANS_LOCK:
        return _PLANS.get(thread_id or current_thread_id())


def set_active_plan(plan: planning.Plan | None, thread_id: str | None = None) -> None:
    """登记 / 替换 / 清除某会话的执行计划（传 None 表示清除）。"""
    with _PLANS_LOCK:
        key = thread_id or current_thread_id()
        if plan is None:
            _PLANS.pop(key, None)
        else:
            _PLANS[key] = plan


@tool
def plan_task(goal: str, steps: str = "") -> str:
    """为复杂任务制定执行计划（多步骤任务专用，简单问题不要调用）。
    什么时候用：任务需要「多个步骤 / 多个库对比 / 先查数再加工再出报告 / 用户明确要流程」时，
    先调用本工具把任务拆成 3~6 步登记下来，再逐步执行。
    goal：一句话目标；steps：可选，用换行或分号分隔的步骤清单，留空则由规划器自动拆解。
    登记后每完成一步都要调用 update_plan 勾选。"""
    thread_id = current_thread_id()
    goal = (goal or "").strip()
    titles = [t.strip() for t in re.split(r"[\n;；]+", steps or "") if t.strip()] if steps else []
    if titles:
        plan = planning.Plan.from_titles(goal or titles[0], titles[:plan_max_steps()], source="manual")
    else:
        plan = create_task_plan(goal) if goal else None
    if plan is None:
        return "（规划失败：请先给出明确目标；也可以不制定计划、直接执行。）"
    set_active_plan(plan, thread_id)
    persist_plan(thread_id, plan)
    return (
        f"已登记执行计划（共 {len(plan.steps)} 步）：\n{plan.to_checklist()}\n"
        "请按顺序执行，每完成一步调用 update_plan(step=序号, status='done', note='产出') 勾选。"
    )


@tool
def update_plan(step: str, status: str = "done", note: str = "") -> str:
    """勾选 / 更新当前执行计划的某一步（每完成一步就调用一次，用户能看到实时进度）。
    step：步骤序号（如 "2"）或标题关键字（如 "汇总对比"）；
    status：done=已完成（默认）/ doing=进行中 / skipped=已跳过 / failed=失败；
    note：可选，本步的产出或说明（如 "医疗库 12 个月收入已取到"）。"""
    plan = get_active_plan()
    if plan is None:
        return "（当前没有执行计划；如需计划请先调用 plan_task。）"
    hit = plan.mark(step, status, note)
    if hit is None:
        return f"（计划里没有找到“{step}”这一步）\n当前计划：\n{plan.to_checklist()}"
    persist_plan(current_thread_id(), plan)
    done, total = plan.progress()
    return (
        f"已更新第 {hit.id} 步 → {planning.STATUS_LABEL.get(hit.status, hit.status)}：{hit.title}"
        f"（进度 {done}/{total}）"
    )


# --------------------------------------------------------------------------- #
# 非结构化表格工具（非结构化数据/ 目录：787 张 markdown / HTML 表格）
# --------------------------------------------------------------------------- #
# 和上面 MySQL 三个业务库是一对镜像能力，但数据源完全不同：
#   MySQL 业务库 → get_table_schema + execute_sql（表结构实时读、SQL 直查）
#   非结构化表格 → describe_table + query_tables（解析成 SQLite 后同样用 SQL 查）
# 之所以让模型写 SQL 而不是写 pandas：sqlite3 是标准库（不用装 pandas），
# 而且模型写 SQL 的准确率更高、与既有 execute_sql 的使用习惯一致。
TABLE_ENABLED = tables.available()


def _ensure_table_index() -> str:
    """确保表格索引可用；返回空串表示正常，否则返回给用户看的提示。"""
    if not TABLE_ENABLED:
        return ("（没有找到 非结构化数据/ 目录或数据文件，表格查询不可用；"
                "可用 TABLE_DATA_DIR 环境变量指定数据目录。）")
    try:
        tables.ensure()
    except Exception as exc:  # noqa: BLE001
        return f"（表格索引构建失败：{exc}）"
    return ""


def _has_cjk(text: str) -> bool:
    """是否含中日韩文字（用来判断要不要补英文关键词检索）。"""
    return bool(re.search(r"[一-鿿]", text or ""))


def _table_keywords(question: str) -> str:
    """把中文问题提炼成英文检索关键词——表格内容以英文为主，纯中文匹配不上。

    只在关键词召回结果太少时才调用（省一次模型调用），失败就安静跳过。
    """
    system = (
        "你是检索关键词提取器。用户会用中文提问，而目标表格里的文字多为英文。\n"
        "请把问题提炼成用于检索表格的英文关键词：一行、空格分隔，包含指标名、公司/产品/地区等专有名词，"
        "必要时给出同义词。只输出关键词本身，不要解释、不要标点、不要中文。"
    )
    try:
        text = _llm_complete(system, question) or ""
    except Exception:
        return ""
    text = re.sub(r"[^\w\s\-\.]", " ", text)
    return " ".join(text.split())[:200]


@tool
def list_table_sets() -> str:
    """列出「非结构化表格库」的全部数据集（规模与适合的问题类型）。

    数据集包括：表格查询 / 领域运算 / 多步检索（三个评测数据文件），
    以及 **files：放进 非结构化数据/ 目录的 Excel / CSV / TSV 表格文件**（若目录里有）。

    什么时候用：用户问的是这些表格里的数据（咖啡消费、气象、电力/新能源、企业财报、
    保险、地区经济，或用户自己放进目录的 Excel/CSV），而不是本机 MySQL 三个业务库
    （金融/医疗/通信）时，先调用本工具确认数据范围，再 find_table 定位表、query_tables 查数。
    注意：这些表格**不在 MySQL 里**，不要用 execute_sql 去查它们。"""
    hint = _ensure_table_index()
    if hint:
        return hint
    sets = tables.list_sets()
    lines = ["非结构化表格库（解析自 非结构化数据/，共 %d 张表）：" % sum(s["tables"] for s in sets)]
    for item in sets:
        lines.append(
            f"- {item['key']}（{item['title']}）：{item['tables']} 张表 / {item['rows']} 行"
            f"（其中 HTML 表 {item['html_tables']}）｜{item['desc']}"
        )
    lines.append("查询流程：find_table 定位候选表 → describe_table 看列名与数值列 → query_tables 写只读 SQL 取数。")
    return "\n".join(lines)


@tool
def analyze_table_query(question: str, dataset: str = "") -> str:
    """【写 SQL 前先做这一步】分析「非结构化表格库」的问题：该查哪个数据集、该用哪些英文检索词、
    这是什么题型、对应 SQL 怎么写、有哪些坑。**纯本地规则，不调用模型也不查库，很快**。

    参数 question：用户问题原文；dataset：可选，限定数据集（table_query / domain_ops / multi_step /
    files=本地 Excel/CSV 文件）。
    返回四块信息：
    ① 数据集判定（按命中词打分，给出建议 dataset）——把它传给 find_table 更准；
    ② 中文术语 → 英文检索词（表内容是英文，这步能显著提升召回，避免关键词对不上）；
    ③ 题型 → 推荐 SQL 写法（占比 / 同比环比 / Top-N / 分组 / 计数 / 求和 / 平均 / 按月趋势 / 反事实 / 取值）；
    ④ 坑提示与建议的调用顺序。
    标准流程：analyze_table_query(问题) → find_table(问题, dataset, keywords) → describe_table → query_tables。"""
    if not TABLE_ENABLED:
        return "（没有找到 非结构化数据/ 目录或数据文件，表格查询不可用。）"
    info = tables.analyze_question(question, dataset=dataset)
    if not info["question"]:
        return "（请给出要分析的问题原文。）"
    lines = [f"问题：{info['question']}"]
    if info["table_id"]:
        lines.append("★ 问题里带了表 id：" + info["table_id"] + "（用它直达，不用再靠关键词猜）")
    lines.append("\n【数据集判定】（分数越高越像；把建议的 dataset 传给 find_table）")
    for item in info["datasets"]:
        hit = ("，命中：" + "、".join(item["hits"])) if item["hits"] else ""
        lines.append(f"- {item['key']}（{item['title']}）得分 {item['score']}{hit}")
    if info["keywords"]:
        lines.append("\n【中文术语 → 英文检索词】（这些词直接放进 find_table 的 keywords 参数）")
        lines.append("、".join(info["keywords"]))
    if info["english"]:
        lines.append("问题里已有的英文词：" + "、".join(info["english"]))
    if info["types"]:
        lines.append("\n【题型 → 推荐 SQL 写法】")
        for item in info["types"]:
            lines.append(f"- {item['label']}")
            lines.append(f"    写法：{item['sql']}")
            lines.append(f"    提示：{item['tips']}")
    else:
        lines.append("\n【题型】未识别到明显题型，按「先看表结构（describe_table）再写最简单的 SELECT」处理。")
    if info["pitfalls"]:
        lines.append("\n【坑提示】")
        for item in info["pitfalls"]:
            lines.append(f"- {item}")
    lines.append("\n【下一步】")
    for item in info["next"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


@tool
def find_table(question: str, dataset: str = "", limit: int = 5, keywords: str = "") -> str:
    """在「非结构化表格库」里按问题召回候选表，返回表 id、行列数、列名与命中词。

    参数 question：用户问题原文；如果问题里带有表 id（15 位十六进制，如 b40962fe65f24d9）会精确命中；
    参数 dataset：可选，限定数据集（table_query / domain_ops / multi_step / files=本地 Excel·CSV，
    或用中文“表格查询/领域运算/多步检索/本地表格”）；
    参数 limit：返回多少张候选表（默认 5）；
    参数 keywords：可选，额外的英文检索词（**用法：先把 analyze_table_query 返回的「中文术语 → 英文检索词」
    填进来**，召回会明显更准；留空时内部会自动做一轮中文术语扩展，必要时还会调用模型补关键词）。
    拿到候选表后：先 describe_table 确认列名，再 query_tables 写 SQL。"""
    hint = _ensure_table_index()
    if hint:
        return hint
    question = (question or "").strip()
    if not question:
        return "（请给出要查的问题原文。）"
    limit = max(1, min(int(limit or 5), 10))
    keywords = (keywords or "").strip()
    hits = tables.find_tables(question, dataset=dataset, limit=limit, extra_keywords=keywords)
    translated = keywords
    # 表内容以英文为主：中文问题命中中文 token 时，多半只是碰巧撞上（"收入""零售"这类），
    # 这时补一轮英文关键词检索再合并，比单靠中文 token 靠谱得多。
    # 已经显式给了 keywords（一般来自 analyze_table_query）就不必再问一次模型。
    needs_translation = not keywords and _has_cjk(question) and (
        len(hits) < 3 or any(_has_cjk(token) for token in hits[0]["matched"])
    )
    if needs_translation:
        translated = _table_keywords(question)
        if translated:
            extra = tables.find_tables(question, dataset=dataset, limit=limit,
                                       extra_keywords=translated)
            merged: dict[str, dict] = {}
            for hit in list(hits) + list(extra):
                old = merged.get(hit["table"])
                if old is None or hit["score"] > old["score"]:
                    merged[hit["table"]] = hit
            hits = sorted(merged.values(), key=lambda item: -item["score"])[:limit]
    if not hits:
        return (f"（没有召回相关表格。可用于检索的英文关键词：{translated or '未生成'}；"
                "可以换一组更具体的词，或先用 list_table_sets 看有哪些数据集。）")
    lines = [f"召回 {len(hits)} 张候选表（按相关度排序）："]
    for index, hit in enumerate(hits, start=1):
        lines.append(
            f"{index}. {hit['table']}（{hit['dataset_title']}，{hit['n_rows']} 行 × {hit['n_cols']} 列，"
            f"相关度 {hit['score']}）\n   列：{'、'.join(str(c) for c in hit['columns'])}"
            f"\n   命中词：{'、'.join(hit['matched'])}"
        )
    if translated:
        lines.append(f"（中文问题已额外用英文关键词检索：{translated}）")
    # 记住这一轮用的是哪张表（query_table_python 没显式传表名时就接着用它）
    _LAST_TABLE["name"] = hits[0]["table"]
    # 自动记忆：① 以前这类问题是怎么查的 ② 上传文件时自动生成的「数据卡片」
    try:
        from services import table_memory
        recalled = table_memory.recall_text(question)
        if recalled:
            lines.append(recalled)
        cards = table_memory.cards_text(limit_chars=900)
        if cards:
            lines.append("【已记住的表格结构（来自上传时自动解析）】\n" + cards)
    except Exception:
        pass
    lines.append("下一步：describe_table(table='候选表id') 看完整列名与数值列；"
                 "SQL 不好写时用 query_table_python 写 Python（df 已注入）。")
    return "\n".join(lines)


@tool
def describe_table(table: str) -> str:
    """看某张非结构化表格的完整列名、数值列、行数与前 3 行预览。

    参数 table：find_table 返回的表名（如 t_b40962fe65f24d9）或 15 位表 id（如 b40962fe65f24d9）。
    数值列已经在解析时清洗成真正的数字（$ 100.00 → 100、23% → 23、括号负数 → 负值），
    可以直接参与算术；写 SQL 时列名要照抄本工具返回的名字，含空格或中文的列名请用双引号包起来。"""
    hint = _ensure_table_index()
    if hint:
        return hint
    detail = tables.table_info(table)
    if not detail:
        return f"（没有找到表 {table}；先用 find_table 召回候选表。）"
    # 预览行也要脱敏：用户放进来的 Excel 常常就是花名册/客户名单（姓名、电话、证件号），
    # 而 query_tables 虽然已脱敏，describe_table 这一步原本会把前几行**原样**吐给模型。
    # 注意 preview 每行是 dict（列名→值），要先按列顺序摊平成值列表再交给 mask_rows。
    columns_raw = [str(c) for c in detail["columns"]]
    raw_preview = [dict(row) for row in (detail.get("preview") or [])]
    matrix = [[row.get(c) for c in columns_raw] for row in raw_preview]
    masked_cols: list = []
    try:
        columns_masked, matrix, masked_cols = sanitize.mask_rows(columns_raw, matrix)
    except Exception:
        columns_masked = columns_raw
    lines = [
        f"{detail['table']}（{detail['dataset_title']}，来源 {detail['source_file']}）",
        f"{detail['n_rows']} 行 × {detail['n_cols']} 列"
        + ("（HTML 表）" if detail["is_html"] else ""),
        "列名：" + "、".join(columns_masked),
        "数值列（可直接算术）：" + ("、".join(str(c) for c in detail["numeric_columns"]) or "无"),
        "前 3 行预览：",
    ]
    for values in matrix:
        lines.append("  " + json.dumps(dict(zip(columns_masked, values)), ensure_ascii=False)[:400])
    note = sanitize.note_for(masked_cols)
    if note:
        lines.append(note)
    lines.append("下一步：query_tables(sql=...) 用只读 SQL 取数（大表请先聚合/筛选，不要 SELECT *）。")
    return "\n".join(lines)


@tool
def query_tables(sql: str, limit: int = 100) -> str:
    """对「非结构化表格库」执行**只读** SQL（SQLite 方言），返回结果表格。

    SQL 规则：只允许单条 SELECT / WITH；表名用 find_table 返回的 t_xxxx，列名照抄 describe_table 的结果
    （含空格/中文的列名用双引号，例如 SELECT "net income" FROM t_xxx WHERE "year" = 2016）；
    数值列已是数字，可以直接做加减乘除、比较、SUM/AVG/ROUND；
    大表（上万行）务必先 WHERE / GROUP BY 聚合，避免 SELECT *。
    参数 limit：最多返回多少行（默认 100，上限 500）。
    结果里的数字都可以直接引用到回答里；查不到就调整 SQL 或换候选表，不要凭空推测。
    查询结果会自动记住：用户要画图/可视化时，取数后直接调用 plot_last_result 即可。"""
    hint = _ensure_table_index()
    if hint:
        return hint
    columns, rows, truncated, error = tables.query(sql, limit=limit)
    if error:
        return ("查询失败：" + error +
                "\n提示：只支持单条 SELECT/WITH；表名用 t_ 开头的那个；列名请照抄 describe_table 的返回。")
    if not columns:
        return "（查询没有返回列；请确认 SQL 是 SELECT 语句。）"
    # 同 execute_sql：表格库的结果同样先脱敏再给模型（这些表里也可能躺着姓名 / 电话）
    columns, rows, masked_cols = sanitize.mask_rows(columns, rows)
    sanitize_note = sanitize.note_for(masked_cols)
    # 缓存最近一次表格库查询结果，供 plot_last_result 画图（与 execute_sql 共用同一个缓存槽）
    _LAST_QUERY["headers"] = [str(c) for c in columns]
    _LAST_QUERY["rows"] = [list(r) for r in rows][:1000]
    _LAST_QUERY["db"] = "tables"
    lines = [" | ".join(str(c) for c in columns), "-" * 40]
    for row in rows:
        lines.append(" | ".join("" if cell is None else str(cell) for cell in row))
    if truncated:
        lines.append(f"（结果被截断，只显示前 {len(rows)} 行；请用 LIMIT 或聚合把范围缩小。）")
    else:
        lines.append(f"（共 {len(rows)} 行）")
    if sanitize_note:
        lines.append(sanitize_note)
    # 数据来源：逐张登记表级出处（数据集名 + 源文件路径），用户能回溯到原始文件
    for tid in re.findall(r"\bt_[A-Za-z0-9_]+", sql)[:5]:
        try:
            info = tables.table_info(tid) or {}
        except Exception:
            info = {}
        record_source(
            "tables", tid,
            label="非结构化表格库 · " + (info.get("dataset_title") or "表格数据"),
            tables=[tid], rows=info.get("n_rows"),
            detail=info.get("source_file") or f"共 {len(rows)} 行参与本次回答",
            sql=sql[:300],
        )
    return "\n".join(lines)


# knowledge/ 目录里有文档才挂载检索工具，避免给 Agent 增加无谓的选项
RAG_ENABLED = bool(rag_service.files())
TOOLS = (
    _BASE_TOOLS
    + [execute_sql, list_database_tables, get_table_schema]  # 直连 MySQL 三个业务库（只读查询 + 实时表结构）
    + [get_db_skill]  # 数据库查询技能卡（skills/database/，业务口径/易错点/模板 SQL）
    + [analyze_query]  # 中文问句关键词抓取与库/表/术语定位（NL→SQL 精准识别）
    + [plot_last_result]  # Matplotlib 可视化：把最近一次查询结果（业务库/表格库）画成图
    + [list_forecast_metrics, forecast_metric]  # sklearn 机器学习月度预测
    # 三级数据能力：初级=SQL 查询（execute_sql/query_tables）· 中级=统计分析与 Python 计算 · 高级=自动建模
    + [run_python]  # 受限 Python 沙箱：对最近一次查询结果做同比环比 / 移动平均 / 线性回归等二次计算
    + [analyze_data, detect_data_anomalies, cluster_data]  # 统计画像/相关分析、异常检测、聚类挖掘
    + [query_table_python]  # 用 Python(pandas) 查表格数据：df 已注入，SQL 不好写的活交给它 + 自动记忆
    + [plan_task, update_plan]  # 规划：任务拆解 + 步骤勾选（复杂任务才会用到）
    + ([list_table_sets, analyze_table_query, find_table, describe_table, query_tables]
       if TABLE_ENABLED else [])
    # 非结构化表格库（非结构化数据/ → SQLite）：本地分析 → 召回 → 看列 → 只读 SQL
    + ([search_knowledge] if RAG_ENABLED else [])
    + [remember, recall, forget]  # 跨会话长期记忆始终可用
)


# 固定规则（System Prompt 的“不变部分”）
# 工具清单直接由 TOOLS 生成，避免提示词里写死一份、注册表里另一份（改工具时不再漏改）
_TOOL_NAMES = "、".join(t.name for t in TOOLS)
_BASE_PROMPT = (
    f"你是「九天梧桐」，一个乐于助人的中文助理"
    f"（用户问“你是谁 / 你叫什么”时，就回答你是九天梧桐），可以使用 {_TOOL_NAMES} 工具。"
    "如果不需要工具就能直接回答，请直接回答；需要工具时，调用合适的工具。\n"
    "记忆规则：不要自作主张保存信息——只有当用户明确说“记住/长期记住/别忘了/帮我记一下”时才调用 remember"
    "（可顺手填 kind=fact/preference/task 与 tags，便于以后按相关度检索）；"
    "当问题涉及用户个人信息或之前会话提到过的事（如“我叫什么、我喜欢什么、我之前说过”），"
    "先调用 recall(query=关键词) 查看跨会话长期记忆，再基于事实回答，绝不编造；"
    "用户明确要求“忘掉/删除某条记忆”时调用 forget，删完如实告知。\n"
    "规划规则：遇到「多步骤任务 / 多对象对比 / 先取数再加工再出报告 / 用户点名要流程」这类复杂任务时，"
    "先用 plan_task(goal) 登记执行计划，再按步骤依次执行；每完成一步立刻调用 update_plan(step=序号, status='done', note=产出) 勾选，"
    "让用户实时看到进度；计划若有变，用 plan_task 重新制定。"
    "反之，简单问题（一次算术、一次查询、闲聊）不要制定计划，直接回答或直接调用工具即可。\n"
    "数据库查询规则：当用户询问业务数据（如客户/患者/用户数量、账单、套餐、就诊、业绩、库存、通话等统计或明细）时，"
    "你需要连接本地 MySQL 的三个业务库查询真实数据后再回答。步骤："
    "① 先判断库并加载技能卡：确定属于哪个库（financial_asset_management 金融 / healthcare_analytics_competition 医疗 / telecom_operations_db 通信）后，"
    "先调用 get_db_skill(database='库名') 加载该库的“查询技能卡”（八张表速览、字段取值与业务口径、易错点、常用模板 SQL；"
    "database 可用中文别名如 '金融/医疗/通信'，留空会返回技能卡清单；同一会话里该库技能卡已加载过就不要重复调用）；"
    "①-附 领域关键词快速定位库：含 套餐/资费/月租/话费/通话/流量/短信/账单/订购/投诉/客服/用户入网 → 通信 telecom_operations_db；"
    "含 理财/产品净值/持仓/交易/收益/亏损/客户资产/风险评级/组合/回撤/夏普 → 金融 financial_asset_management；"
    "含 患者/就诊/住院/门诊/药品/库存/医嘱/医保/结算/设备/体检 → 医疗 healthcare_analytics_competition"
    "（关键词重叠时以“套餐、药费、理财”等最明确的业务对象定库，再按需要 get_db_skill 确认）；\n"
    "用户问句口语化或拿不准库/表/口语词对应字段时，先调用 analyze_query(问题原文) 抓取关键字与关键提示词"
    "（返回判库、疑似表、术语对照、动作与时间写法提示），再据此加载技能卡与核对表结构；不确定表名时再运行 list_database_tables；"
    "② 用 get_table_schema 获取相关表的真实字段结构（列名/类型/主键/注释），据此精准编写 SQL，"
    "表名与列名必须与返回的真实结构完全一致，严禁凭印象编造不存在的列名；"
    "技能卡与模板 SQL 仅为参考，与真实表结构冲突时一律以 get_table_schema 为准；"
    "③ 用 execute_sql 执行只读 SELECT 查询真实数据库（裸表名不重名时会自动识别所属库，重名或跨库请用 库名.表名）；"
    "③-附 关键词→写法速查：问“最便宜/最低/最贵/最高/最大/最小/排名前 N/低于 X 元/超过 X 元”"
    "→ ORDER BY 对应数值字段（ASC=取最小、DESC=取最大）+ LIMIT，并先加“当前有效/在售/现网”过滤"
    "（产品目录通信用 is_current=1、金融用 is_active=1，订购关系用当前生效条件），限定范围后再排序；"
    "“多少个/人数/条数/笔数/次数/家数”→ COUNT（按人/客户去重用 COUNT(DISTINCT 主键))，“多少钱/总金额/合计”→ SUM，"
    "“平均/均值”→ AVG，“每个/各/按…分组”→ GROUP BY 后聚合，“占比/分布/比例”→ 分组计数再算比率；"
    "“近 30 天/本月/上月/去年/近一年”→ 时间范围过滤（先看时间列类型：医疗是真 DATETIME，金融是 VARCHAR ISO 串，"
    "金融月度聚合用 LEFT(col,7)，医疗可直接日期比较）；"
    "业务同义词先归一为真实字段再写：套餐月租/资费=通信 products.base_fee、理财费率=金融 products.management_fee（小数费率 0.01=1%/年）、"
    "单次就诊费用=医疗 medical_encounters.total_cost、结算净额=billing_transactions.net_amount，拿不准就先 get_table_schema 看列注释；"
    "③-附 失败自纠与防空转：execute_sql 返回“执行失败 / 无法自动确定所在库”时，必须先读懂错误属于连接、库名、表名、列名还是语法，"
    "修正后最多重试一次；同一句 SQL 连续两次失败就禁止原样再发——改用 get_table_schema 复核该表真实列名、把语句拆简单"
    "（先 SELECT * FROM 库.表 LIMIT 5 看真实数据再写），仍不可行就如实告知用户数据库当前不可用，绝不重复空转；"
    "④ 技能卡与真实表结构仍无法确定字段业务含义时，才可用 search_knowledge 检索“自然语言→SQL”文档辅助理解，冲突仍以真实表结构为准；"
    "⑤ 拿到查询结果后用中文直接回答用户，给出关键数字与结论，明细多时用 Markdown 表格，严禁编造数据；"
    "若结果提示“仅显示前 N 行 / 共 M 行”而用户要看完整数据，应如实告知或用 COUNT/分组聚合再查询。\n"
    "可视化规则：当用户要求“画图 / 可视化 / 走势图 / 占比分布”时，先查到要展示的数据"
    "（业务库用 execute_sql、非结构化表格库用 query_tables，两者都会自动记住最近一次查询结果），"
    "随后调用 plot_last_result(title=…, x_col=…, y_cols=…) 生成图表；"
    "最终回复必须直接引用它返回的图片地址（![标题](/reports/文件名.png)），不要编造图片地址；"
    "若用户没明说画什么，默认画“最近一次查询结果的趋势/对比图”。\n"
    "预测规则：当用户要求“预测 / 未来某个月 / 趋势走向 / 用机器学习(Sklearn)模型 / 生成预测报告”时，"
    "先调用 list_forecast_metrics 查看可用指标（金融/医疗/通信三个库各有月度指标），选对应 key 后调用 "
    "forecast_metric(metric=..., horizon=月数) 完成 sklearn 建模预测；若用户说“所有/三个数据库都要”，则对三个库各选代表指标依次调用。"
    "工具会返回各月预测值与趋势结论，并自动生成 reports/*.md 预测报告文件；回复时直接给出关键预测数字、趋势结论和报告文件路径，不要描述内部建模步骤。\n"
    "回复风格（务必遵守，目标是“像一位靠谱的同事在帮你干活”，既专业又有人味）：\n"
    "① 先给结论再给依据：开头一两句就把答案说清楚（关键数字加粗），明细多时再用 Markdown 表格；\n"
    "② 说人话：用自然、温和的中文口语，把数字背后的意思讲出来（涨了还是跌了、和谁比、说明了什么），"
    "必要时补一句实在的建议或提醒，而不是只甩一张表；\n"
    "③ 不要“机器味”：不复述用户的问题、不罗列“我先…然后…最后”的执行步骤、不出现 SQL / 工具名 / "
    "“分析步骤”这类内部信息，也不要把回答拆成问题拆解式的结构化小标题；\n"
    "④ 可以有一点人味：开头允许一句自然的承接（如“查到了”“这个数挺有意思”“先说结论”），但最多一句；"
    "长期记忆里如果有用户的称呼，可以偶尔自然地用一次，不要每次都用；\n"
    "⑤ 结尾可以给一个自然的下一步（如“要不要顺手看看同比”，最多一句），但不要每轮都问、不要连问两个问题；\n"
    "⑥ 拿不准就直说：数据查不到、口径有歧义、工具失败时，先如实说明情况，再说明你按什么假设给出了结果，"
    "并给一个可行的替代方案，而不是冷冰冰地报错；\n"
    "⑦ 时间与问候：涉及时间时以系统给出的当前时间为准；早中晚的问候要贴合当时时间，不要硬套；\n"
    "⑧ 表情符号：只在闲聊、安慰或道谢时偶尔用一两个，正式的数据结论与业务建议里不要用；\n"
    "⑨ 数据来源不用你在正文里罗列：本轮用到的数据（哪个库的哪些表 / 哪份知识库文档 / 哪次预测 / 哪张图表）"
    "系统会自动生成「数据来源」卡片附在回答下方；你不用在正文写“数据来源：xxx 表”；"
    "但如果数字是估算的、口径有假设、或数据来自被截断的结果，必须在正文里说清楚；\n"
    "信息不足需要补充时，直接说明缺什么、并默认按合理假设给出结果即可（不要停下来等用户确认）。"
)
if RAG_ENABLED:
    _BASE_PROMPT += (
        "你还可以使用 search_knowledge 检索本地知识库（产品手册、FAQ、内部政策等人工整理资料）。"
        "当问题涉及这些文档化资料（如产品如何使用、政策规定）时必须先检索相关文档，再基于检索到的原文回答，并注明参考了哪个文件；"
        "检索不到相关内容时请如实说明没有找到，不要编造。\n"
    )
if TABLE_ENABLED:
    _BASE_PROMPT += (
        "非结构化表格规则：你还有一套「非结构化表格库」工具（list_table_sets / find_table / "
        "describe_table / query_tables），数据是 非结构化数据/ 目录下解析出来的 700+ 张 markdown / HTML 表格"
        "（咖啡消费、气象、电力与新能源、企业财报、保险、地区经济等）。"
        "当用户问的是这些表格里的数据时——问题里带表 id（15 位十六进制）、提到「表格 / 这张表 / 第几行第几列」，"
        "或者问的领域明显不在 MySQL 三个业务库里——就按这个流程走："
        "① analyze_table_query(问题原文) 先做本地分析（不花钱）：它会给出【数据集判定】【中文术语→英文检索词】"
        "【题型→推荐 SQL 写法】【坑提示】，并直接告诉你下一步怎么调；"
        "② find_table(question=问题原文, dataset=第①步建议的数据集, keywords=第①步给的英文检索词) 定位候选表"
        "（问题里带表 id 会精确命中；没给 keywords 时内部会自动扩展中文术语，必要时再调模型补词）；"
        "③ describe_table(table=表名) 看完整列名与数值列，确认口径；"
        "④ query_tables(sql=...) 写**只读 SQLite SQL** 取数：表名用 t_xxxx，列名照抄 describe_table 的结果，"
        "含空格或中文的列名用双引号；数值列已清洗成真正的数字，可直接算术（$ 100.00→100、23%→23、括号→负数）；\n"
        "②-附 关键词→写法速查：问「占比 / 比重 / 百分比」→ SUM(部分)*100.0/SUM(整体)；"
        "问「同比 / 环比 / 增长 / 变化率」→ 先取到两个数再 (v2-v1)*100.0/v1（跨月可用 LAG 窗口函数）；"
        "问「最多 / 最少 / 排名 / 前 N」→ ORDER BY 数值 DESC/ASC LIMIT N；问「每个 / 各 / 按…」→ GROUP BY 后聚合；"
        "问「多少 / 几个」→ COUNT，问「多少种 / 多少人」→ COUNT(DISTINCT ...)；问「合计 / 总额」→ SUM；"
        "问「平均」→ AVG；问「按月 / 趋势」→ GROUP BY substr(日期列,1,7)；"
        "问「假设…没有发生」→ 反事实：先在明细里定位该事件再剔除重算，不要对现成合计做减法；"
        "问「哪一列 / 第一行 / 某个单元格」→ 直接 SELECT 该列（小表 SELECT * LIMIT 3 看全貌）。\n"
        "⑤ 大表（上万行）先 WHERE / GROUP BY 聚合，不要 SELECT *；"
        "⑥ 失败自纠：SQL 报错先查列名是否照抄（含空格/中文必须加引号）、表名是否 t_ 开头、是否只写了一条 SELECT；"
        "召回不对就换关键词或直接跟用户要表 id；连续两次不行就如实说明，不要重复空转；"
        "⑦ 回答直接引用 SQL 结果里的数字，不要心算；用户要画图/可视化时，query_tables 取数后直接调用 plot_last_result 即可出图"
        "（它会自动记住最近一次查询结果）。"
        "注意：这些表格**不在 MySQL 里**，不要用 execute_sql 查它们；反过来三个业务库的问题也不要用 query_tables。"
    )


# --------------------------------------------------------------------------- #
# System Prompt 与 Dynamic Prompt
# --------------------------------------------------------------------------- #
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


def build_system_prompt(
    now: datetime | None = None,
    plan: "planning.Plan | None" = None,
    summary: str | None = None,
    tools: list[str] | None = None,
) -> str:
    """渲染 System Prompt（Dynamic Prompt）。

    - “System Prompt”：把角色 + 工具规则整段作为系统消息固定注入。
    - “Dynamic Prompt”：同一套模板里留出运行时才有的变量，每次问答前重新渲染：

      * 当前时间 / 星期几 → 问“现在几点”可直接回答，不必等工具；
      * **本轮执行计划**（planning.Plan）→ 复杂任务先拆解再按步执行，用户能看到进度；
      * **早期对话摘要**（长会话记忆压缩）→ 上下文既记得住又不爆炸；
      * **本轮注册的工具**（tools）→ 工具清单替换成实际子集，并附一行一个的用途/参数约束。

    合成走 `core/context.compose()`：各块标注优先级，自动跨块去重，
    超过 `CTX_BUDGET` 预算时**从低优先级块开始丢**（`) optional 块先丢`）。
    合成报告留在 `build_system_prompt.last_report`，便于评估脚本统计上下文用量。
    """
    """渲染 System Prompt（Dynamic Prompt）。

    - “System Prompt”：把角色 + 工具规则整段作为系统消息固定注入。
    - “Dynamic Prompt”：同一套模板里留出运行时才有的变量，每次问答前重新渲染：

      * 当前时间 / 星期几 → 问“现在几点”可直接回答，不必等工具；
      * **本轮执行计划**（planning.Plan）→ 复杂任务先拆解再按步执行，用户能看到进度；
      * **早期对话摘要**（长会话记忆压缩）→ 上下文既记得住又不爆炸。

    三个参数都有默认值，因此 `build_system_prompt()` 的老用法（固定 system_prompt
    注入 create_agent）完全不受影响。
    """
    now = now or datetime.now()
    time_text = (
        f"今天是 {now:%Y-%m-%d}（星期{WEEKDAYS[now.weekday()]}），当前时间 {now:%H:%M:%S}。"
        "基于该时间回答“现在几点、今天星期几”之类问题，无需再调用工具。"
    )
    role_text = _BASE_PROMPT if not tools else _BASE_PROMPT.replace(
        _TOOL_NAMES, "、".join(tools))       # 工具清单替换成本轮实际注册的那批

    # 关闭 CTX 时保持与改造前完全一致的行为（纯拼接）
    if not context.enabled():
        parts = [time_text]
        if summary:
            parts.append("【本会话早期对话摘要（长会话记忆压缩，供你延续上下文）】\n"
                         + summary.strip()
                         + "\n（摘要未覆盖的细节若不确定，请向用户确认，不要编造。）")
        parts.append(role_text)
        parts.append(prompting.guardrails_block(tables_ready=bool(TABLE_ENABLED)))
        parts.append(context.ROUTING_RULES)     # 路由规则在两种模式下都给，避免知识题跑 SQL
        if reasoning.cot_enabled():
            parts.append(reasoning.COT_RULES)
        if plan is not None and getattr(plan, "steps", None):
            parts.append(_plan_system_hint(plan))
        return "\n\n".join(parts)

    # 上下文工程：每个块带**优先级**，合成时自动去重、超预算从低优先级块开始丢
    blocks: list[context.Block] = [
        context.block("time", time_text, optional=False),
        context.block("role", role_text, optional=False),
        # 清单式约束单独成块：比起塞在长段落里，模型对这种「写 SQL 前必查 / 回答前必查」
        # 的编号清单遵循率明显更高（散落的经验规则在这里收敛成一张 checklist）
        context.block("safety", prompting.guardrails_block(tables_ready=bool(TABLE_ENABLED)),
                      optional=False),
        # 冲突时的取舍顺序 + 一个正面示例（priorities + few-shot）
        context.block("example", context.PRIORITY_RULES + "\n" + context.ANSWER_EXAMPLE),
        # 第一层路由：先把「问数据」和「问制度」分开（知识类问题跑 SQL 是最常见的偏航）
        context.block("task", context.ROUTING_RULES, optional=False),
    ]
    if summary:
        blocks.append(context.block(
            "memory",
            "【本会话早期对话摘要（长会话记忆压缩，供你延续上下文）】\n" + summary.strip()
            + "\n（摘要未覆盖的细节若不确定，请向用户确认，不要编造。）"))
    if plan is not None and getattr(plan, "steps", None):
        blocks.append(context.block("task", _plan_system_hint(plan), optional=False))
    if reasoning.cot_enabled():
        blocks.append(context.block("hint", reasoning.COT_RULES))
    if tools:                                # 本轮注册的工具：一行一个（用途 + 参数约束）
        blocks.append(context.block("hint", context.render_tool_guide(tools)))

    prompt, report = context.compose(blocks)
    build_system_prompt.last_report = report
    return prompt


build_system_prompt.last_report = {}   # 最近一次 System Prompt 的合成报告（供评估统计）


_KB_KEYWORDS: list[str] = []          # 从知识库文档动态抽取的主题词（缓存）
_KB_KEYWORDS_STAMP: float = 0.0
_KB_KEYWORDS_TTL = 300.0              # 5 分钟刷新一次，跟着用户的知识库走


def knowledge_keywords() -> list[str]:
    """把知识库文档的**文件名 + 各级标题**抽成路由关键词。

    这样替换/新增知识库文档后，意图路由会自动适应——不用回来改规则表。
    """
    global _KB_KEYWORDS, _KB_KEYWORDS_STAMP
    now = time.time()
    if _KB_KEYWORDS and now - _KB_KEYWORDS_STAMP < _KB_KEYWORDS_TTL:
        return _KB_KEYWORDS
    words: set[str] = set()
    sources: set[str] = set()
    # ① 文件名：从已建索引的文档元信息里取，也顺带上 knowledge/ 目录里的新文件
    try:
        rag_service._ensure()            # 首次访问时构建索引（拿到 _documents）
        for doc in list(getattr(rag_service, "_documents", []) or []):
            source = str((doc.metadata or {}).get("source", ""))
            if source:
                sources.add(source)
    except Exception:
        pass
    try:
        for path in rag_service.directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in (".md", ".markdown", ".txt", ".pdf"):
                sources.add(str(path.relative_to(KNOWLEDGE_DIR)))
    except Exception:
        pass
    for source in sources:
        stem = Path(source).stem or source
        for token in re.split(r"[_\-\s（）()【】、,，]+", stem):
            if len(token) >= 2 and re.search(r"[\u4e00-\u9fff]", token):
                words.add(token)

    # ② 标题：文档的各级标题是极强的路由信号（如「住宿标准」「市内交通与餐饮」）
    try:
        for source in sources:
            path = rag_service.directory / source
            if not path.exists() or path.suffix.lower() not in (".md", ".markdown", ".txt"):
                continue
            head = path.read_text(encoding="utf-8", errors="ignore")[:20000]
            for line in head.splitlines():
                line = line.strip()
                # 只取二级以内的小节标题：三级标题通常是「1 列出所有姓王的客户信息」
                # 这种问答样例，拿它们当路由词会把数据类问题误判到知识库
                matched = re.match(r"^#{1,2}\s+(?!\d)(.+)$", line)
                if not matched:
                    continue
                title = matched.group(1).strip(" 。：:")
                if 2 <= len(title) <= 20:
                    words.add(title)
                for token in re.split(r"[与和及/（）()、,，\s]+", title):
                    if len(token) >= 2 and re.search(r"[\u4e00-\u9fff]", token):
                        words.add(token)
    except Exception:
        pass
    cleaned = sorted({w for w in words if len(w) >= 2 and len(w) <= 20})
    _KB_KEYWORDS, _KB_KEYWORDS_STAMP = cleaned, now
    return _KB_KEYWORDS


def select_tools_for(question: str, task_type: str | None = None) -> tuple[list, dict]:
    """上下文工程：按任务阶段挑选本轮要注册的工具，返回 (工具对象列表, 报告)。

    工具不是越多越好——26 个工具全量注册时，模型既要消化大量 schema，还容易"选择困难"。
    这里按问题意图只注册用得上的那一组（核心工具永远保留），通常能省下三到五成工具上下文；
    出错或无法判断时**返回全量**，宁可多给也不给漏。
    """
    if not context.enabled():
        return list(TOOLS), {"groups": [], "kept": len(TOOLS), "dropped": 0, "reduction": 0.0}
    try:
        names, report = context.select_tools(
            question, task_type=task_type, available=[tool.name for tool in TOOLS],
            knowledge_keywords=knowledge_keywords())
        if not names:
            return list(TOOLS), {"groups": [], "kept": len(TOOLS), "dropped": 0, "reduction": 0.0}
        subset = [tool for tool in TOOLS if tool.name in set(names)]
        return subset, report
    except Exception:
        return list(TOOLS), {"groups": [], "kept": len(TOOLS), "dropped": 0, "reduction": 0.0}


# 手写 ReAct 循环（流式输出用）的常量
TOOL_MAP = {tool.name: tool for tool in TOOLS}

# 工具名的“人话”说法：前端拿它显示「正在查询业务数据库…」这类自然进度，
# 而不是把 execute_sql / forecast_metric 这种内部名字怼给用户看。
TOOL_LABELS = {
    "calculator": "正在算数",
    "get_current_time": "正在看时间",
    "word_count": "正在数字数",
    "execute_sql": "正在查询业务数据库",
    "list_database_tables": "正在翻数据库目录",
    "get_table_schema": "正在核对表结构",
    "get_db_skill": "正在翻这个库的业务口径",
    "analyze_query": "正在琢磨你的问法",
    "plot_last_result": "正在画图",
    "list_forecast_metrics": "正在看有哪些指标能预测",
    "forecast_metric": "正在跑预测模型",
    "run_python": "正在用 Python 计算",
    "analyze_data": "正在做统计分析",
    "detect_data_anomalies": "正在检测异常数据",
    "cluster_data": "正在做聚类分群",
    "query_table_python": "正在用 Python 分析表格",
    "search_knowledge": "正在翻知识库文档",
    "remember": "正在把这件事记下来",
    "recall": "正在回忆你之前说过的事",
    "forget": "正在删掉那条记忆",
    "plan_task": "正在把任务理成几步",
    "update_plan": "正在更新计划进度",
    "list_table_sets": "正在看有哪些表格数据",
    "analyze_table_query": "正在拆解这个问题要怎么查",
    "find_table": "正在找相关的数据表",
    "describe_table": "正在看这张表的列结构",
    "query_tables": "正在查表格数据",
}


def tool_label(name: str) -> str:
    """把工具名换成给用户看的自然说法（未登记的工具有回退文案）。"""
    return TOOL_LABELS.get(name) or f"正在使用 {name}"
MAX_STEPS = 40  # 模型“调用工具→再想”的最大轮数；放宽后多步骤任务（三库预测对比、连续查询）不会轻易被截断
MAX_REPEAT_TOOL = 3  # 同一工具且参数完全相同连续出现 N 次 → 判定模型陷入死循环，提前终止


# --------------------------------------------------------------------------- #
# 模型服务商（多服务商可切换，默认 DeepSeek：快且便宜）
# --------------------------------------------------------------------------- #
# 每个预设：key_env = 读哪个环境变量拿密钥；base_url / model 同理
PROVIDER_PRESETS = {
    "deepseek": {
        "key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "key_env": "OPENAI_API_KEY",
        "base_url_env": "BASE_URL",
        "default_base_url": "",
        "model_env": "MODEL",
        "default_model": "gpt-3.5-turbo",
    },
}
DEFAULT_PROVIDER = "deepseek"
PROVIDER_CHAIN = ("deepseek", "openai")  # 首选 → 备用：DeepSeek 失败后自动落到 openai(haoapi)

# ---- 渠道健康状态：某服务商调用失败后进入冷却期，期间请求自动改用备用渠道 ----
_PROVIDER_FAILED_AT: dict[str, float] = {}
_PROVIDER_COOLDOWN_SECONDS = float(os.getenv("PROVIDER_COOLDOWN_SECONDS", "300"))


def _provider_in_cooldown(name: str) -> bool:
    return time.monotonic() - _PROVIDER_FAILED_AT.get(name, 0.0) < _PROVIDER_COOLDOWN_SECONDS


def mark_provider_failed(name: str) -> None:
    """记录某服务商刚调用失败：进入冷却期后，后续请求会自动跳过它改用备用渠道。"""
    _PROVIDER_FAILED_AT[name] = time.monotonic()
    print(
        f"[provider] {name} 接口调用失败，已标记冷却 {_PROVIDER_COOLDOWN_SECONDS:.0f}s，"
        "后续请求将自动切换备用渠道",
        file=sys.stderr,
    )


def resolve_provider(name: str | None = None) -> str:
    """决定当前用哪个服务商：显式指定(参数/LLM_PROVIDER) > 谁配了密钥就用谁。

    按 PROVIDER_CHAIN 顺序挑选：优先 DeepSeek；若 DeepSeek 处于失败冷却期则自动选
    备用渠道 openai，实现“首选不可用自动切换”。
    """
    explicit = (name or os.getenv("LLM_PROVIDER") or "").strip().lower()
    ordered: list[str] = []
    if explicit in PROVIDER_PRESETS:
        ordered.append(explicit)
    for cand in PROVIDER_CHAIN:
        if cand not in ordered and os.getenv(PROVIDER_PRESETS[cand]["key_env"]):
            ordered.append(cand)
    if not ordered:  # 都没配密钥：仍按首选顺序返回，由 build_llm 提示缺 key
        ordered = list(PROVIDER_CHAIN)
    for cand in ordered:
        if not _provider_in_cooldown(cand):
            return cand
    return ordered[0]  # 全部在冷却期：返回首选，交给调用方尝试并再次标记


def build_llm(
    provider: str | None = None,
    model: str | None = None,
    *,
    force: bool = False,
) -> ChatOpenAI:
    """构造 ChatOpenAI。

    provider 不指定时走 resolve_provider() 的自动选路；force=True 时跳过冷却判断，
    强制使用指定服务商（用于备用渠道的主动重试）。
    """
    if force:
        if provider not in PROVIDER_PRESETS:
            raise ValueError(f"未知服务商：{provider}")
        name = provider
    else:
        name = resolve_provider(provider)
    preset = PROVIDER_PRESETS[name]

    api_key = os.getenv(preset["key_env"])
    if not api_key:
        raise RuntimeError(
            f"未找到 {preset['key_env']}，请在 .env 中配置（参考 .env.example）；"
            f"或把 LLM_PROVIDER 改成其它已配置的服务商"
        )

    base_url = os.getenv(preset["base_url_env"]) or preset["default_base_url"]
    kwargs = {
        "model": model or os.getenv(preset["model_env"]) or preset["default_model"],
        "api_key": api_key,
        "temperature": 0,
        "timeout": float(os.getenv("REQUEST_TIMEOUT", "60")),
        "max_retries": int(os.getenv("MAX_RETRIES", "1")),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def provider_info(provider: str | None = None) -> dict:
    """给 /api/health 用的服务商概况（不含密钥）。"""
    provider = resolve_provider(provider)
    preset = PROVIDER_PRESETS[provider]
    return {
        "provider": provider,
        "model": os.getenv(preset["model_env"]) or preset["default_model"],
        "base_url": os.getenv(preset["base_url_env"]) or preset["default_base_url"] or "官方默认",
        "key_configured": bool(os.getenv(preset["key_env"])),
    }


def build_checkpointer():
    """返回 (checkpointer, backend_name)。优先 SQLite 持久化，失败退回内存。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver(), "memory"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    return SqliteSaver(conn), "sqlite"


def build_agent(checkpointer=None):
    if checkpointer is None:
        checkpointer, _ = build_checkpointer()
    return create_agent(
        model=build_llm(),
        tools=TOOLS,
        system_prompt=build_system_prompt(),
        checkpointer=checkpointer,
        store=get_store()[0],  # 挂载跨会话 Store（长期记忆）
    )


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _textify(content) -> str:
    """部分模型返回的是分块列表，统一转成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


# 自动起标题时先剥掉的客套开头（让侧栏标题更像人写的，而不是原样搬运问题）
_TITLE_PREFIXES = ("请帮我", "帮我", "麻烦你", "麻烦", "请", "能不能", "可以帮我", "我想", "我要", "帮忙")


def make_title(question: str) -> str:
    """用第一条用户消息自动命名会话：去掉客套开头与结尾标点，过长再截断。"""
    original = " ".join((question or "").split()).strip()
    title = original
    for prefix in _TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):].lstrip("，,、:： ")
            break
    title = title.strip("？?。！!，,;；:： ").strip()
    if not title:
        title = original          # 全被剥掉（如只说了“帮我”）就退回原文
    return title[:TITLE_MAX_LEN] + ("…" if len(title) > TITLE_MAX_LEN else "")


def last_ai_message(messages) -> str:
    for message in reversed(messages or []):
        if getattr(message, "type", "") == "ai" and _textify(getattr(message, "content", "")):
            # 跳过“工具调用前的过程句”，只认最终回答
            if getattr(message, "tool_calls", None):
                continue
            return _textify(message.content)
    return ""


def to_plain_messages(messages) -> list[dict]:
    """把 LangChain 消息对象转成前端可直接渲染的 {role, content}。

    只保留“用户的提问”和“AI 的最终回答”：AI 在调用工具前写下的过程句
    （其后紧跟 ToolMessage 的那条 AI 消息）只用于模型上下文，不展示。
    """
    msg_list = list(messages or [])
    plain = []
    for i, message in enumerate(msg_list):
        kind = getattr(message, "type", "")
        text = _textify(getattr(message, "content", ""))
        if kind == "human" and text:
            plain.append({"role": "user", "content": text})
        elif kind == "ai" and text:
            nxt = msg_list[i + 1] if i + 1 < len(msg_list) else None
            if getattr(message, "tool_calls", None):
                continue  # 带工具调用 = 过程轮，跳过
            if getattr(nxt, "type", "") == "tool":
                continue  # 后跟工具结果 = 过程句，跳过
            plain.append({"role": "assistant", "content": text})
    return plain


# --------------------------------------------------------------------------- #
# 智能搜索 / 深度搜索（RAG 增强）
# --------------------------------------------------------------------------- #
# 分层说明：
#   智能搜索（smart_search / search_knowledge 工具）
#     = 关键词 [+ 语义向量] 多路召回 + RRF 融合重排；
#       可选 RAG_RERANK=1 时再加一轮 LLM 相关度重排（默认关闭以省时省钱）。
#   深度搜索（ChatService.stream_deep / --deep / /api/deep）
#     = Deep-Research 式：拆解子问题 → 逐个子查询智能检索 → 查漏补缺（第二轮）
#       → 候选去重 + 可选 LLM 重排 → 带 [1][2]… 引用的综合回答。
# 环境变量：DEEP_PLAN_MAX=4（子查询数）、DEEP_ROUND2=1（是否做查漏补缺）、
#   DEEP_RERANK=1（综合前是否 LLM 重排）、DEEP_PER_QUERY=5（每个子查询召回数）、
#   DEEP_EVIDENCE=10（最终采纳的片段上限）、RAG_RERANK=0（检索工具是否额外 LLM 重排）。
def _env_flag(name: str, default: bool = False) -> bool:
    """读取 0/1 布尔环境变量；变量未设置或为空时用 default，
    显式设置为 0/false/off 时必须能关闭（即使 default=True）。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int | None = None,
             maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _next_backup_provider(provider: str) -> str | None:
    """返回备用服务商（当前渠道失败冷却时切换），没有则 None。"""
    return next(
        (p for p in PROVIDER_CHAIN if p != provider and os.getenv(PROVIDER_PRESETS[p]["key_env"])),
        None,
    )


def _llm_complete(system: str, user: str) -> str:
    """非流式调用一次 LLM（失败自动切一次备用渠道），返回纯文本。"""
    llm, provider = _build_llm_once()
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    try:
        resp = llm.invoke(messages)
    except Exception:
        backup = _next_backup_provider(provider)
        if backup is None:
            raise
        mark_provider_failed(provider)
        llm = build_llm(backup, force=True)
        resp = llm.invoke(messages)
    return _textify(resp.content)


def _llm_stream_text(system: str, user: str) -> Iterator[str]:
    """流式调用 LLM 输出正文（失败自动切一次备用渠道），逐段产出文本。"""
    llm, provider = _build_llm_once()
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    fallback_used = False
    try:
        for chunk in llm.stream(messages):
            text = _textify(getattr(chunk, "content", None))
            if text:
                yield text
    except Exception:
        backup = _next_backup_provider(provider)
        if backup is None or fallback_used:
            raise
        mark_provider_failed(provider)
        fallback_used = True
        llm = build_llm(backup, force=True)
        for chunk in llm.stream(messages):
            text = _textify(getattr(chunk, "content", None))
            if text:
                yield text


def _build_llm_once() -> tuple[ChatOpenAI, str]:
    provider = resolve_provider()
    return build_llm(provider=provider, force=True), provider


def _chunk_snippet(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------- #
# 规划（Planning）核心：制定计划 / 注入提示词 / 落盘
# --------------------------------------------------------------------------- #
# 三种模式（PLAN_MODE）：
#   auto   —— 默认：由 planning.needs_plan() 启发式判断，复杂任务才规划（省时省钱）
#   always —— 每个问题都先规划
#   off    —— 完全关闭规划，回到「模型直接 ReAct」的老行为
# 规划相关开关**全部运行时读取**（与深度搜索的 DEEP_* 一致）：
# 这样命令行 --plan、测试脚本或临时改环境变量都能立刻生效，不用重新导入模块。
PLAN_REUSE_CUES = ("继续", "接着", "下一步", "按计划", "继续执行", "还没做", "剩下的")

# 最近一次用到的表格库表名（供 query_table_python 在没显式传表名时接着用）
_LAST_TABLE: dict[str, str] = {}

# 最近一次「树状搜索」的候选路线与评分（由 create_task_plan 写入，stream_ask 渲染进提示词）
_REASON_TRAIL: dict[str, "reasoning.Trail"] = {}


def plan_mode() -> str:
    """当前规划模式：auto / always / off（非法值一律按 auto）。"""
    raw = (os.getenv("PLAN_MODE", "auto") or "auto").strip().lower()
    return raw if raw in ("auto", "always", "off") else "auto"


def planning_enabled() -> bool:
    return plan_mode() != "off"


def plan_max_steps() -> int:
    """计划最多几步（PLAN_MAX_STEPS，默认 6）。"""
    return _env_int("PLAN_MAX_STEPS", 6, minimum=1, maximum=12)


def plan_reflect_enabled() -> bool:
    """终答前是否做一次执行自检（PLAN_REFLECT，默认开）。"""
    return _env_flag("PLAN_REFLECT", True)


def plan_max_reflect() -> int:
    """自检后最多再继续几轮（PLAN_MAX_REFLECT，默认 1）。"""
    return _env_int("PLAN_MAX_REFLECT", 1, minimum=0, maximum=3)


def plan_tool_hint() -> str:
    """给规划器看的工具清单（只给名字，够它把每一步落到真实能力上）。"""
    return "、".join(t.name for t in TOOLS)


def create_task_plan(goal: str, context: str = "") -> "planning.Plan | None":
    """调用规划器把目标拆成执行计划；失败返回 None（整条链路自动降级为「不规划」）。

    复杂任务（planning.needs_plan 判定）会走 core/reasoning 的树状搜索：
    ToT 多路径探索或 MCTS 规划搜索，并把候选路线的评分记到 _REASON_TRAIL 里，
    由 stream_ask 渲染成「推理路径」注入提示词；任何异常都退回单条计划。
    """
    try:
        complex_task = bool(planning.needs_plan(goal)[0])
        plan, trail = reasoning.plan_with_strategy(
            _llm_complete, goal, tools_hint=plan_tool_hint(), context=context,
            strategy=None, base_steps=plan_max_steps(), complex_task=complex_task,
        )
        if trail is not None and trail.events:
            _REASON_TRAIL["last"] = trail
        if plan is not None:
            plan.source = "auto"
        return plan
    except Exception:
        return planning.make_plan(_llm_complete, goal, tools_hint=plan_tool_hint(),
                                  max_steps=plan_max_steps(), context=context)


def should_reuse_plan(question: str) -> bool:
    """判断本轮是不是「接着上一轮的计划继续做」（继续 / 下一步 / 按计划…）。"""
    text = question or ""
    return any(cue in text for cue in PLAN_REUSE_CUES)


_PLAN_RULES = (
    "【执行计划（Planning）】本轮已为你制定好执行计划，请严格按计划推进：\n"
    "{checklist}\n"
    "执行要求：① 按顺序执行，每完成一步立刻调用 update_plan(step=序号, status='done', note='本步产出') 勾选；"
    "② 只做计划内的事，不跳步、不做与目标无关的事；"
    "③ 计划明显不合理时用 plan_task 重新制定（新计划自动替换旧计划）；"
    "④ 全部步骤完成后，直接用中文给出最终结果与结论——不要复述计划、步骤或操作过程。"
)


def _plan_system_hint(plan) -> str:
    """把计划渲染成注入 System Prompt 的执行规则（Dynamic Prompt 的一部分）。"""
    return _PLAN_RULES.format(checklist=plan.to_checklist())


def _history_snippets(messages, limit: int = 6) -> list[str]:
    """把最近几轮消息压成「用户：… / 助手：…」的短文本，供查询理解补全指代。"""
    out: list[str] = []
    for msg in list(messages or [])[-limit:]:
        role = getattr(msg, "type", "") or ""
        text = _textify(getattr(msg, "content", None)).strip().replace("\n", " ")
        if not text:
            continue
        if isinstance(msg, HumanMessage) or role == "human":
            out.append("用户：" + text[:200])
        elif role == "ai" or "AI" in type(msg).__name__:
            out.append("助手：" + text[:200])
    return out


def _understand_question(question: str, messages=None) -> dict | None:
    """一次便宜的结构化调用，产出 QuerySpec（见 prompting 模块）。

    失败一律返回 None：查询理解是**增强项**而非必需项，模型不可用 / 返回非 JSON /
    超时都不该影响正常问答。是否触发由 prompting.worth_understanding() 本地判断
    （闲聊、寒暄、纯算术不浪费这次调用），总开关 QUND=0 可关。
    """
    if not prompting.enabled():
        return None
    try:
        return prompting.understand(
            question, _history_snippets(messages), datetime.now(), complete=_llm_complete,
        )
    except Exception:
        return None


def planning_summary() -> dict:
    """规划概况（模式 / 参数 / 当前挂着的计划数），用于 /api/health。"""
    with _PLANS_LOCK:
        active = len(_PLANS)
    return {
        "mode": plan_mode(),
        "max_steps": plan_max_steps(),
        "reflect": plan_reflect_enabled(),
        "max_reflect": plan_max_reflect(),
        "active_plans": active,
    }


def _plan_brief(plan) -> dict:
    """给前端的最小计划结构（目标 + 步骤 + 进度）。"""
    data = plan.to_dict()
    return {
        "goal": data["goal"],
        "steps": data["steps"],
        "progress": data["progress"],
        "source": data["source"],
        "revision": data["revision"],
    }


def _status_map(plan) -> dict:
    """{步骤 id: 状态} 快照，用来比对出「哪些步骤发生了变化」。"""
    if plan is None:
        return {}
    return {step.id: step.status for step in plan.steps}


def _plan_events(plan, snapshot: dict) -> tuple[list[dict], dict]:
    """比对计划前后状态，产出 plan_step 事件与最新快照。"""
    if plan is None:
        return [], snapshot
    events = []
    for step in plan.steps:
        if snapshot.get(step.id) != step.status:
            events.append({"type": "plan_step", "step": step.to_dict()})
    return events, _status_map(plan)


def restore_plan(thread_id: str) -> "planning.Plan | None":
    """从会话元数据恢复上次的执行计划。

    计划同时存在于「内存注册表」和 data/conversations.json：服务重启后内存是空的，
    这时说一句「继续」也能把上次没跑完的计划捞回来接着做。
    """
    if not thread_id:
        return None
    try:
        item = default_conversation_store().get(thread_id) or {}
        return planning.Plan.from_dict(item.get("plan") or {})
    except Exception:
        return None


def _prepare_plan(thread_id: str, question: str) -> tuple["planning.Plan | None", list[dict]]:
    """为本轮问答准备执行计划（规划入口），返回 (计划, 需要先推给前端的事件)。

    - PLAN_MODE=off：不规划；
    - 用户说“继续 / 下一步 / 按计划”：沿用上一轮还没跑完的计划（跨轮次任务不断档）；
    - PLAN_MODE=auto：由 planning.needs_plan() 判定，只有复杂任务才多花一次模型调用；
    - 规划失败：静默降级为“直接执行”，绝不打断对话。
    """
    if not planning_enabled():
        set_active_plan(None, thread_id)
        return None, []
    if should_reuse_plan(question):
        existing = get_active_plan(thread_id) or restore_plan(thread_id)
        if existing is not None and existing.pending():
            set_active_plan(existing, thread_id)   # 重新挂到内存注册表，后续 update_plan 才能勾选
            brief = _plan_brief(existing)
            brief.update({"type": "plan", "reason": "沿用上一轮未完成的计划", "restored": True})
            return existing, [brief]
    need, reason = planning.needs_plan(question)
    if plan_mode() != "always" and not need:
        set_active_plan(None, thread_id)   # 简单问题：清掉旧计划，避免把上一轮的计划误注入本轮
        return None, []
    plan = create_task_plan(question)
    if plan is None:
        return None, []                    # 规划失败：安静降级，不打断对话
    set_active_plan(plan, thread_id)
    persist_plan(thread_id, plan)
    brief = _plan_brief(plan)
    brief.update({"type": "plan", "reason": reason})
    thinking = {"type": "thinking", "message": "让我先把这件事理成几步…"}
    return plan, [thinking, brief]


def _apply_reflection(plan, decision: dict, thread_id: str, snapshot: dict) -> tuple[list[dict], dict]:
    """把自检结果应用到计划（修正步骤状态 / 追加新步骤），返回 (事件, 新快照)。"""
    if plan is None:
        return [], snapshot
    for update in decision.get("updates") or []:
        plan.mark(update.get("step"), update.get("status") or planning.DONE, update.get("note") or "")
    new_titles = [str(t).strip() for t in (decision.get("steps") or []) if str(t).strip()]
    if new_titles and len(plan.steps) < plan_max_steps() * 2:
        plan.add_steps(new_titles[:3])
    events, snapshot = _plan_events(plan, snapshot)
    if events:
        persist_plan(thread_id, plan)
    return events, snapshot


def persist_plan(thread_id: str | None, plan) -> None:
    """把计划与进度写进会话元数据（data/conversations.json），刷新页面后仍能看到。"""
    if not thread_id or plan is None:
        return
    try:
        store = default_conversation_store()
        if store.get(thread_id):
            store.update(thread_id, plan=plan.to_dict(), plan_updated_at=_now())
    except Exception:
        pass  # 计划落盘失败不影响本轮回答


# --------------------------------------------------------------------------- #
# 长会话记忆压缩（Summary Memory）
# --------------------------------------------------------------------------- #
# 对话很长时，把「较早的消息」压成一段滚动摘要，只把「摘要 + 最近若干条原文」发给模型：
#   * 上下文长度可控（不会越聊越慢、越聊越贵）；
#   * 早期约定过的事仍然记得住（摘要是增量的，不是重新生成）；
#   * Checkpointer 里的完整历史一条都没删，界面上依然是全量对话。
# 环境变量：MEM_COMPACT=1 开关、MEM_COMPACT_AFTER=40 触发条数、MEM_COMPACT_KEEP=12 保留原文条数。
DIGEST_NS = ("thread_digest",)


def _digest_config() -> tuple[bool, int, int]:
    enabled = _env_flag("MEM_COMPACT", True)
    after = _env_int("MEM_COMPACT_AFTER", 40, minimum=8, maximum=2000)
    keep = _env_int("MEM_COMPACT_KEEP", 12, minimum=2, maximum=400)
    return enabled, after, keep


def _message_text(message) -> str:
    """把一条消息转成摘要用的可读文本（工具结果只留片段，避免摘要被数据淹没）。"""
    kind = getattr(message, "type", "")
    text = _textify(getattr(message, "content", ""))
    if not text.strip():
        return ""
    if kind == "human":
        return f"用户：{text.strip()}"
    if kind == "ai":
        return f"助手：{text.strip()}"
    if kind == "tool":
        return f"工具结果：{_chunk_snippet(text, 300)}"
    return _chunk_snippet(text, 300)


def get_thread_digest(thread_id: str) -> dict | None:
    """读取某会话的滚动摘要：{"summary": str, "upto": 已覆盖的消息条数}。"""
    if not thread_id:
        return None
    try:
        store, _ = get_store()
        item = store.get(DIGEST_NS, thread_id)
    except Exception:
        return None
    value = dict(getattr(item, "value", None) or {}) if item is not None else {}
    return value or None


def _save_thread_digest(thread_id: str, summary: str, upto: int) -> None:
    try:
        store, _ = get_store()
        store.put(DIGEST_NS, thread_id, {
            "summary": summary, "upto": int(upto), "updated_at": _now(),
        })
    except Exception:
        pass


def build_thread_digest(thread_id: str, messages: list, previous: str = "") -> str:
    """增量生成滚动摘要：已有摘要 + 新覆盖的消息 → 新摘要；失败返回空串。"""
    lines = [line for line in (_message_text(m) for m in messages) if line]
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > 12000:                      # 一次喂太多反而慢：只摘最近的部分
        body = body[-12000:]
    system = (
        "你在为一个长对话做「滚动摘要」，用于压缩上下文又不丢关键信息。\n"
        "把对话压缩成不超过 400 字的中文摘要，必须保留：\n"
        "1. 用户的身份、偏好，以及明确要求记住的事实；\n"
        "2. 已经查到的关键数字、结论与出处；\n"
        "3. 已经做出的决定、未完成的待办与遗留问题。\n"
        "不要写客套话，不要复述问题。只输出摘要正文。"
    )
    user = (f"【已有摘要（更早的对话）】\n{previous}\n\n【需要并入摘要的新对话】\n{body}"
            if previous else f"【需要压缩的对话】\n{body}")
    try:
        return (_llm_complete(system, user) or "").strip()
    except Exception:
        return ""


def prepare_history(thread_id: str, history: list) -> tuple[list, str]:
    """长会话压缩：返回 (发给模型的历史消息, 早期对话摘要)。

    - 未开启 / 消息不多：原样返回，行为与老版本完全一致；
    - 触发压缩但摘要生成失败：退回全量历史（宁可长一点，也不丢上下文）。
    """
    enabled, after, keep = _digest_config()
    if not enabled or len(history) <= after:
        return history, ""
    # 切片边界对齐：窗口不能以 ToolMessage 开头 —— 那意味着它的 tool_calls 被切在窗外，
    # 发送给模型会触发 DeepSeek 400（tool 消息必须响应前置 tool_calls）。向左扩展至调用组起点。
    start = max(0, len(history) - keep)
    while start > 0 and type(history[start]).__name__ == "ToolMessage":
        start -= 1
    older, recent = history[:start], history[start:]
    digest = get_thread_digest(thread_id) or {}
    upto = int(digest.get("upto") or 0)
    if digest.get("summary") and upto >= len(older) - 2:
        return recent, str(digest.get("summary"))
    summary = build_thread_digest(thread_id, older, previous=str(digest.get("summary") or ""))
    if not summary:
        return history, str(digest.get("summary") or "")
    _save_thread_digest(thread_id, summary, len(older))
    return recent, summary


def _sanitize_tool_pairs(history: list) -> list:
    """修复消息断链，避免 DeepSeek 400（tool 消息必须紧跟其 tool_calls 组）。

    - 无前置 tool_calls 的 ToolMessage（孤儿工具结果）→ 丢弃；
    - 没有任何工具响应的悬空 tool_calls → 去掉 tool_calls（保留文字内容，如有）。
    只在“发送给模型前”清洗，不改写 Checkpointer 里的完整历史。
    """
    out: list = []
    i, n = 0, len(history)
    while i < n:
        m = history[i]
        name = type(m).__name__
        if name == "ToolMessage":
            i += 1  # 孤儿工具结果：丢弃
            continue
        tcs = getattr(m, "tool_calls", None) or []
        if name == "AIMessage" and tcs:
            j = i + 1
            while j < n and type(history[j]).__name__ == "ToolMessage":
                j += 1
            if j > i + 1:  # 该组有工具响应：整组保留
                out.append(m)
                out.extend(history[i + 1:j])
                i = j
                continue
            text = _textify(getattr(m, "content", None))
            if text:
                out.append(AIMessage(content=text))  # 悬空 tool_calls：降级为纯文字
            i += 1
            continue
        out.append(m)
        i += 1
    return out


def _strip_code_fence(text: str) -> str:
    """去掉代码围栏（解析逻辑统一放在 planning 模块，这里只是历史调用点的薄封装）。"""
    return planning.strip_code_fence(text)


def _extract_string_list(text: str) -> list[str]:
    """容错解析字符串数组（解析实现统一在 planning.parse_string_list，避免两套实现）。"""
    return planning.parse_string_list(text)


def _extract_score_map(text: str) -> dict[int, float]:
    """解析重排打分：期望 {"1": 9, "2": 5, ...}；失败返回空 dict。"""
    if not text:
        return {}
    cleaned = _strip_code_fence(text)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    scores: dict[int, float] = {}
    for key, value in data.items():
        try:
            scores[int(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return scores


# ------------------------------ 智能搜索：可插 LLM 重排 ------------------------------ #
def _rerank_by_llm(query: str, docs: list, top_n: int) -> tuple[list, bool]:
    """对已召回的片段做一轮 LLM 相关度打分重排，返回 (重排后的 docs, 是否成功)。

    打分对象是 0~10 的整数（10 最相关），输出 JSON 对象 {"编号": 分数, ...}。
    解析失败时保持原顺序返回，不影响上层流程。
    """
    if len(docs) <= top_n or not docs:
        return docs, False
    lines = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "?")
        lines.append(f"{i}. [{source}] {_chunk_snippet(doc.page_content, 180)}")
    system = (
        "你是信息检索重排器。下面给出针对某个查询从知识库召回的候选片段，"
        "请判断每个片段与查询的相关程度，给 0~10 的整数分（10=高度相关、直接回答查询）。\n"
        "只输出一个 JSON 对象：{\"1\": 分数, \"2\": 分数, ...}，键是片段编号，不要输出任何其它文字。"
    )
    user = f"查询：{query}\n\n候选片段：\n" + "\n".join(lines)
    try:
        scores = _extract_score_map(_llm_complete(system, user))
    except Exception:
        return docs, False
    if not scores:
        return docs, False
    ordered = sorted(enumerate(docs), key=lambda item: scores.get(item[0] + 1, -1.0), reverse=True)
    return [doc for _, doc in ordered][:top_n], True


def _format_knowledge_hits(docs: list, engines_label: str) -> str:
    """把检索片段拼成给 Agent 的文本（带来源/页码/相关度标注），风格与 rag.search 一致。"""
    if not docs:
        return "（知识库中没有检索到与问题相关的内容，请如实告知用户，不要编造。）"
    parts = [f"（检索引擎：{engines_label}）"]
    for index, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "未知文档")
        chunk_index = doc.metadata.get("chunk_index", "?")
        page = doc.metadata.get("page")
        score = doc.metadata.get("score")
        head = f"片段{index}（来源：{source} · 第{chunk_index}段"
        if page is not None:
            head += f" · PDF 第{page}页"
        if score is not None:
            head += f" · 相关度{score:.3f}"
        parts.append(f"{head}）：\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(parts)


def _knowledge_text(docs: list, engines_label: str) -> str:
    """把检索结果拼成给模型的文本（空结果沿用 rag.search 的提示口径，避免模型乱猜）。"""
    if docs:
        return _format_knowledge_hits(docs, engines_label)
    if "知识库为空" in engines_label or "检索失败" in engines_label:
        return f"（{engines_label}。请如实告知用户，不要编造知识库中的信息。）"
    if "空查询" in engines_label:
        return "（检索内容不能为空。）"
    return "（知识库中没有检索到与问题相关的内容，请如实告知用户，不要编造。）"


def _record_knowledge_sources(docs: list) -> None:
    """把命中片段的“出自哪个文档第几段/第几页”登记成数据来源。"""
    for doc in docs or []:
        meta = getattr(doc, "metadata", {}) or {}
        source = meta.get("source") or "未知文档"
        page = meta.get("page")
        where = f"PDF 第{page}页 · 第{meta.get('chunk_index', '?')}段" if page is not None \
            else f"第{meta.get('chunk_index', '?')}段"
        record_source("knowledge", source, detail=where)


def smart_search(query: str) -> str:
    """search_knowledge 工具的智能检索入口：多路召回 + RRF 融合（可选 + LLM 重排）。

    统一走 retrieve() 拿结构化片段：既能沿用旧文案，又能把出处登记成数据来源。

    检索上下文管线（core/context）：
      查询改写 → 扩大候选池多路召回 → **查询词覆盖率重排** → **同源限流**
      → 相关性阈值过滤（全部太低就是"证据不足"，不硬凑）
      → 来源标注（路径/段落/页码/更新时间/相关度）→ 按段落裁剪到 CTX_SNIPPET
    """
    # ① 查询改写：口语提问里的寒暄、口水词会直接影响相似度，先洗掉
    search_query = context.rewrite_query(query) if context.enabled() else query
    # ② 先多召回一些：**单个来源限流**（context.diversify）需要有富余候选才起作用
    #    ——否则知识库里的大文档会靠篇幅包揽名额，把真正命中的小文档挤出去
    pool = max(RAG_TOP_K * 4, 12) if context.enabled() else None
    if not _env_flag("RAG_RERANK"):
        docs, engines_label = rag_service.retrieve(search_query, k=pool or RAG_TOP_K, mode="smart")
    else:
        docs, engines_label = rag_service.retrieve(
            search_query, k=max(pool or RAG_PER_LIST, RAG_PER_LIST), mode="smart")
        if docs:
            reranked, ok = _rerank_by_llm(search_query, docs, RAG_TOP_K)
            if ok:
                engines_label += " → LLM 相关度重排"
                docs = reranked
    if context.enabled():
        # ③ 查询词覆盖率重排：单纯的融合排名会被大文档的"高频词刷榜"压过去，这里补一维
        docs = context.rerank_by_coverage(docs, search_query)
        # ④ 同源限流：同一来源最多占一半名额，别让一篇大文档包揽全部 Top-K
        docs = context.diversify(docs, limit=RAG_TOP_K,
                                 max_per_source=max(1, -(-RAG_TOP_K // 2)))
    # ②③④ 阈值过滤 + 来源标注 + 长度裁剪（关 CTX 时保持原样输出）
    if docs and context.enabled():
        text = context.build_retrieved_context(docs, engines_label, query=search_query)
        if "所有候选片段的相关度" in text:      # 全部未过阈值：按旧口径给"没查到"
            docs = []
            text = _knowledge_text(docs, engines_label)
    else:
        text = _knowledge_text(docs, engines_label)
    _record_knowledge_sources(docs)
    # 知识库原文里也可能带个人信息（人事通知、报销样例等），进模型上下文之前先脱敏
    return sanitize.mask_text(text)


# ------------------------------ 深度搜索（Deep Research 式） ------------------------------ #
def _deep_plan_queries(question: str, max_queries: int) -> list[str]:
    """深度搜索第一步：把问题拆成若干子查询。

    提示词与解析已统一到 planning.research_queries（原先这里单独有一份实现），
    函数名保持不变，_iter_deep_search 等既有调用点无需改动。
    """
    return planning.research_queries(_llm_complete, question, max_queries)


def _doc_key(doc) -> str:
    meta = doc.metadata
    return f"{meta.get('source', '?')}|{meta.get('chunk_index', '?')}|{meta.get('page') or ''}"


def _gap_fill_queries(question: str, evidence: dict) -> list[str]:
    """查漏补缺：判断已有资料是否足够；不够则给出 1~2 个新子查询（返回 [] 表示已足够）。

    提示词与解析已统一到 planning.gap_queries；这里只负责把证据池整理成摘要文本。
    """
    snippets = []
    for index, entry in enumerate(evidence.values(), start=1):
        if index > 12:
            break
        doc = entry["doc"]
        snippets.append(f"（{doc.metadata.get('source', '?')}）{_chunk_snippet(doc.page_content, 160)}")
    return planning.gap_queries(_llm_complete, question, snippets)


def _deep_sources(items: list) -> list[dict]:
    """把最终采纳的片段整理成前端可展示的来源列表。"""
    sources = []
    for index, doc in enumerate(items, start=1):
        sources.append({
            "index": index,
            "source": doc.metadata.get("source", "未知文档"),
            "chunk_index": doc.metadata.get("chunk_index", "?"),
            "page": doc.metadata.get("page"),
            "score": doc.metadata.get("score"),
            "engines": doc.metadata.get("engines", []),
            "snippet": sanitize.mask_text(_chunk_snippet(doc.page_content, 140)),
        })
    return sources


def _iter_deep_search(question: str) -> Iterator[dict]:
    """深度搜索主流程（生成器）：产出 plan/search/gap/token/sources/answer 等事件。

    事件类型：
      {"type": "info",   ...}           深度搜索开始 / 引擎情况
      {"type": "plan",   "queries": []} 子问题拆解结果
      {"type": "search", "query": str, "hits": int, "engines": str, "round": 1|2}
      {"type": "gap",    "queries": []} 查漏补缺阶段发现的新子查询（可无）
      {"type": "rerank", "count": int}   对候选做了 LLM 重排
      {"type": "token",  "content": str} 综合回答的正文增量
      {"type": "sources", "items": []}   参考来源
      {"type": "answer", "answer": str, "sources": []}  本轮结束（供外层落盘/收尾）
    """
    question = (question or "").strip()
    if not question:
        yield {"type": "answer", "answer": "（问题不能为空。）", "sources": []}
        return

    rag_service._ensure()
    if not rag_service.files():
        yield {"type": "answer",
               "answer": "（知识库为空：请先把 .md/.txt/.pdf 文档放入 knowledge/ 目录。深度搜索需要基于知识库资料。）",
               "sources": []}
        return

    info = rag_service.summary()
    yield {"type": "info",
           "message": f"知识库共 {info['chunk_count'] or 0} 个片段 / {info['file_count']} 个文档",
           "backend": info["backend"]}

    max_plan = min(max(_env_int("DEEP_PLAN_MAX", 4), 1), 6)
    per_query = max(_env_int("DEEP_PER_QUERY", 5), 1)
    evidence_cap = max(_env_int("DEEP_EVIDENCE", 10), 1)
    do_gap = _env_flag("DEEP_ROUND2", True)
    do_rerank = _env_flag("DEEP_RERANK", True)

    # ① 拆解子问题
    queries = _deep_plan_queries(question, max_plan)
    yield {"type": "plan", "queries": queries}

    # ② 逐个子查询智能检索 → 去重证据池
    evidence: dict[str, dict] = {}

    def _search_round(sub_query: str, round_no: int) -> Iterator[dict]:
        docs, engines_label = rag_service.retrieve(sub_query, k=per_query, mode="smart")
        hits = 0
        for doc in docs:
            key = _doc_key(doc)
            score = float(doc.metadata.get("score", 0.0))
            old = evidence.get(key)
            if old is None:
                evidence[key] = {"doc": doc, "best": score}
            else:
                old["best"] = max(old["best"], score)
                old["doc"].metadata["engines"] = sorted(
                    set((old["doc"].metadata.get("engines") or []) + (doc.metadata.get("engines") or []))
                )
            hits += 1
        yield {"type": "search", "query": sub_query, "hits": hits, "engines": engines_label, "round": round_no}

    for q in queries:
        yield from _search_round(q, 1)

    # ③ 查漏补缺（第二轮，最多 2 个补充子查询）
    gap_queries: list[str] = []
    if do_gap and evidence:
        try:
            gap_queries = _gap_fill_queries(question, evidence)
        except Exception:
            gap_queries = []
        if gap_queries:
            yield {"type": "gap", "queries": gap_queries}
            for q in gap_queries:
                yield from _search_round(q, 2)

    if not evidence:
        yield {"type": "answer",
               "answer": "（在知识库中未检索到与问题相关的资料，无法完成检索式综合回答。请补充相关文档后再试。）",
               "sources": []}
        return

    # ④ 按多轮最优相关度收敛候选 → LLM 相关度重排后再截取（剔除弱相关片段）
    ranked_entries = sorted(evidence.values(), key=lambda item: item["best"], reverse=True)
    pool = [entry["doc"] for entry in ranked_entries]
    reranked = False
    if do_rerank and len(pool) > 1:
        # 最多给重排器 14 个融合分靠前的候选（控制 LLM 调用成本）
        candidates = pool[:min(len(pool), 14)]
        selected, reranked = _rerank_by_llm(question, candidates, evidence_cap)
        pool = selected if reranked else pool[:evidence_cap]
    else:
        pool = pool[:evidence_cap]
    if reranked:
        yield {"type": "rerank", "count": len(pool)}

    final_items = [doc for doc in pool if doc.page_content.strip()]
    sources = _deep_sources(final_items)
    if not final_items:
        yield {"type": "answer", "answer": "（知识库中没有检索到可作答的原文片段。）", "sources": []}
        return

    # ⑤ 综合回答（带 [1]…[n] 引用），流式输出正文
    snippet_lines = []
    for i, doc in enumerate(final_items, start=1):
        meta = doc.metadata
        loc = meta.get("source", "?")
        if meta.get("page") is not None:
            loc += f"（PDF 第{meta['page']}页 · 第{meta.get('chunk_index')}段）"
        else:
            loc += f"（第{meta.get('chunk_index')}段）"
        snippet_lines.append(f"[{i}] 出自 {loc}：\n{sanitize.mask_text(doc.page_content.strip())}")
    system = (
        "你是知识库研究员。根据下面给出的知识库原文片段（带 [编号] 引用），用中文完整、准确地回答用户问题。\n"
        "要求：\n"
        "1. 只依据片段原文作答，不得编造片段里没有的事实与数字；\n"
        "2. 在能支撑结论的句子后标注来源编号，如 ……[1]、……[2]；同一片段可多次引用；\n"
        "3. 组织成通顺的回答：先给结论/要点，再展开细节；信息确实不足时如实说明缺口；\n"
        "4. 不使用「根据片段 1/资料 2」这类说法，只用 [1][2] 标注。"
    )
    user = (f"用户问题：{question}\n\n以下是检索到的知识库原文片段：\n"
            + "\n\n".join(snippet_lines))
    answer_parts: list[str] = []
    san = sanitize.StreamSanitizer()   # 流式：跨 chunk 的号码不能漏，交给增量脱敏器
    try:
        for token in _llm_stream_text(system, user):
            text = san.push(token)
            if not text:
                continue
            answer_parts.append(text)
            yield {"type": "token", "content": text}
    except Exception as exc:
        yield {"type": "error", "message": f"综合回答生成失败：{exc}"}
        return

    answer = sanitize.mask_text("".join(answer_parts)).strip() or "（未能生成回答内容。）"
    yield {"type": "sources", "items": sources}
    yield {"type": "answer", "answer": answer, "sources": sources}


# --------------------------------------------------------------------------- #
# 会话元数据仓库
# --------------------------------------------------------------------------- #
class ConversationStore:
    """会话元数据（标题 / 时间 / 消息数）的 JSON 持久化，带写锁。"""

    def __init__(self, path: Path = CONVERSATIONS_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data = self._read()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            try:
                backup = self.path.with_suffix(".json.corrupt")
                if not backup.exists():
                    self.path.replace(backup)
            except OSError:
                pass
            return {}

    def _reload(self) -> None:
        """写盘前先从磁盘重新读一次，避免多进程互相覆盖。

        网页服务、命令行、脚本常常是**不同进程**同时读写这个文件，而每次写盘都是整文件
        覆盖：谁最后写谁赢，会把另一个进程刚建好的会话整条抹掉（表象就是“会话莫名其妙
        不见了”）。所以改数据之前先合并一次磁盘内容——这样最多丢同一会话的并发字段更新，
        不会再丢会话本身。
        读不到或内容损坏时**保持内存里的版本**，绝不因为一次读失败就把别人的会话清空。
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._data = data

    def _write(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def create(self, title: str | None = None) -> dict:
        now = _now()
        thread_id = uuid.uuid4().hex[:12]
        item = {
            "id": thread_id,
            "title": ((title or "").strip()[:60] or DEFAULT_TITLE),
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        with self._lock:
            self._reload()          # 先合并磁盘上其它进程写入的会话，再落盘
            self._data[thread_id] = item
            self._write()
        return dict(item)

    def get(self, thread_id: str) -> dict | None:
        with self._lock:
            item = self._data.get(thread_id)
            return dict(item) if item else None

    def list(self) -> list[dict]:
        with self._lock:
            self._reload()          # 列表是用户直接看到的，取磁盘最新，避免显示陈旧会话
            items = [dict(v) for v in self._data.values()]
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return items

    def update(self, thread_id: str, **fields) -> dict | None:
        with self._lock:
            self._reload()
            if thread_id not in self._data:
                return None
            self._data[thread_id].update(fields)
            item = dict(self._data[thread_id])
            self._write()
        return item

    def delete(self, thread_id: str) -> dict | None:
        with self._lock:
            self._reload()
            item = self._data.pop(thread_id, None)
            if item:
                self._write()
            return dict(item) if item else None

    def clear(self) -> list:
        """清空全部会话元数据，返回被清掉的 thread_id 列表（用于连带清理检查点）。

        注意：本类的 list 是实例方法，这里刻意没有写成 `list[str]` 注解
        （类体里该名字已被方法遮蔽，会触发 TypeError）。
        """
        with self._lock:
            self._reload()
            ids = list(self._data.keys())
            if not ids:
                return []
            self._data = {}
            self._write()
            return ids


# 默认会话仓库做成模块级单例：plan_task / update_plan 这类工具需要把计划进度
# 落到「同一个」会话元数据文件上，多实例各持一份内存缓存会互相覆盖。
_DEFAULT_CONVERSATION_STORE: dict = {"store": None}
_default_store_lock = threading.RLock()


def default_conversation_store() -> ConversationStore:
    """返回默认的会话元数据仓库（进程内单例，落盘 data/conversations.json）。"""
    with _default_store_lock:
        if _DEFAULT_CONVERSATION_STORE["store"] is None:
            _DEFAULT_CONVERSATION_STORE["store"] = ConversationStore()
        return _DEFAULT_CONVERSATION_STORE["store"]


# --------------------------------------------------------------------------- #
# 多会话服务
# --------------------------------------------------------------------------- #
class ChatService:
    """在单个 Agent（单个 Checkpointer）之上管理多个互不干扰的会话线程。"""

    def __init__(self, store: ConversationStore | None = None):
        self.store = store or default_conversation_store()
        # RLock：ask() 里会在持锁状态下访问 agent 属性（懒加载同样要加锁）
        self._lock = threading.RLock()
        self._agent = None
        self._checkpointer = None
        self._backend = None

    # -- Agent 懒加载 ------------------------------------------------------- #
    @property
    def agent(self):
        if self._agent is None:
            with self._lock:
                if self._agent is None:
                    checkpointer, backend = build_checkpointer()
                    self._checkpointer = checkpointer
                    self._backend = backend
                    self._agent = create_agent(
                        model=build_llm(),
                        tools=TOOLS,
                        system_prompt=build_system_prompt(),
                        checkpointer=checkpointer,
                        store=get_store()[0],  # 同一个 Store 实例，跨会话共享
                    )
        return self._agent

    @property
    def backend(self) -> str:
        self.agent  # 触发初始化
        return self._backend or "memory"

    def info(self) -> dict:
        """服务商 + Checkpointer + Store + 知识库 + 规划概况，供 /api/health 使用（不强制初始化模型客户端）。"""
        return {
            **provider_info(),
            "checkpointer": self._backend or "未初始化（首次提问时启用）",
            "conversations": len(self.store.list()),
            "store": store_summary(),
            "rag": rag_service.summary(),
            "database": database_status(),
            "planning": planning_summary(),
            "memory": memory_summary(),
            "tables": tables_summary(),
        }

    # -- 会话管理 ----------------------------------------------------------- #
    def new_conversation(self, title: str | None = None) -> dict:
        return self.store.create(title)

    def list_conversations(self) -> list[dict]:
        return self.store.list()

    def rename_conversation(self, thread_id: str, title: str) -> dict | None:
        title = (title or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        return self.store.update(thread_id, title=title[:60], updated_at=_now())

    def delete_conversation(self, thread_id: str) -> dict | None:
        """删除元数据，并顺带清掉该 thread 在 Checkpointer 中的全部检查点。"""
        item = self.store.delete(thread_id)
        if item and self._checkpointer is not None:
            try:
                self._checkpointer.delete_thread(thread_id)
            except Exception:
                pass  # 内存版或旧版本不支持删除，忽略即可
        return item

    def clear_conversations(self) -> int:
        """一键清空全部会话：元数据 + 各 thread 在 Checkpointer 里的对话历史一起清掉。

        返回被清掉的会话数（供前端提示“已清空 N 个会话”）。
        """
        thread_ids = self.store.clear()
        if self._checkpointer is not None:
            for thread_id in thread_ids:
                try:
                    self._checkpointer.delete_thread(thread_id)
                except Exception:
                    pass  # 内存版或旧版本不支持删除，忽略即可
        return len(thread_ids)

    def history(self, thread_id: str) -> list[dict]:
        """从 Checkpointer 中读取某个 thread 的完整对话历史。"""
        try:
            state = self.agent.get_state({"configurable": {"thread_id": thread_id}})
        except Exception:
            return []
        if not state or not state.values:
            return []
        return to_plain_messages(state.values.get("messages", []))

    # -- 问答 --------------------------------------------------------------- #
    def _ensure_thread(self, thread_id: str | None, question: str) -> str:
        """校验问题并返回可用的 thread_id（传了不存在的 thread 会自动新建）。"""
        if not (question or "").strip():
            raise ValueError("问题不能为空")
        if not thread_id or not self.store.get(thread_id):
            thread_id = self.store.create()["id"]
        return thread_id

    def ask(self, thread_id: str | None, question: str) -> dict:
        """在指定会话中提问（一次性返回完整回答）；thread_id 为空时自动新建会话。

        **重合功能合并**：本方法不再单独走 create_agent.invoke()，而是复用 stream_ask()
        的同一个执行引擎（记忆压缩 → 规划 → 工具执行 → 自检 → 落盘），把 token 事件
        拼成完整回答。这样命令行 / demo / 网页三个入口的行为完全一致，不会再出现
        “网页有计划、命令行没有计划”这类两套逻辑漂移。
        """
        thread_id = self._ensure_thread(thread_id, question)
        answer = ""
        error: str | None = None
        for event in self.stream_ask(thread_id, question):
            kind = event.get("type")
            if kind == "token":
                answer += event.get("content", "")
            elif kind == "error":
                error = event.get("message") or "未知错误"
            elif kind == "done" and event.get("answer"):
                answer = event["answer"]          # 以 done 事件里的完整回答为准
        if error:
            raise RuntimeError(error)
        return {"thread_id": thread_id, "answer": answer, "messages": self.history(thread_id)}

    def stream_ask(self, thread_id: str | None, question: str, skill: str = "") -> Iterator[dict]:
        """在指定会话中提问，逐 token 产出流式事件（本项目的**唯一执行引擎**）。

        Agent = LLM(大脑) + Planning(规划) + Tool use(执行) + Memory(记忆)，五步走：

        ① **记忆**：取该会话历史；对话很长时用「滚动摘要 + 最近原文」压缩上下文
           （MEM_COMPACT），Checkpointer 里的完整历史一条不删；
        ② **规划**：复杂任务（PLAN_MODE=auto 时由 planning.needs_plan 判定）先拆成
           执行计划并注入 System Prompt；说“继续/下一步”则沿用上一轮未完成的计划；
        ③ **执行**：绑定工具的 ReAct 循环，逐 token 流式产出；模型每完成一步会调用
           update_plan 勾选，进度实时以 plan_step 事件推给前端；
        ④ **自检**：终答前由自检器核对计划是否真的完成（PLAN_REFLECT），没完成就带着
           指令再补一轮（最多 PLAN_MAX_REFLECT 次）；
        ⑤ **落盘**：本回合消息写回 Checkpointer，计划进度写回会话元数据。

        为什么不让 create_agent 直接流式？它内部每个模型节点都走 model.invoke()
        （一次性等完整回答），不会吐出中间 token。这里在 Agent 之外自己跑一个
        “绑定工具的 ReAct 循环”，整轮结束再用 graph.update_state() 把新回合追加进
        Checkpointer（与 invoke 路径等价，多会话记忆与历史读取不受影响）。

        参数 skill：可选，用户在 Web 页面上手动指定的数据技能卡（库 key 或中文别名，
        如 'financial_asset_management' / '医疗'）；指定后当轮会注入“手动指定数据范围”
        指令，强制按该库加载技能卡与查询；空串 = 自动识别（默认）。

        事件 dict 依次可能产出：
          {"type": "thinking",  "message": str}   过程提示（如“正在制定执行计划”）
          {"type": "plan",      "goal", "steps", "progress"}  本轮执行计划
          {"type": "plan_step", "step": {...}}    计划某一步的状态变化
          {"type": "token", "content": str}   文本增量（前端逐字拼出回答）
          {"type": "rewind", "chars": n}      回滚 n 个字符（模型在调工具前写的过渡句要撤回）
          {"type": "tool",  "name": str}       某工具开始执行
          {"type": "sources","items": [...]}   本轮用到的数据来源（库/表/文档/预测/图表）
          {"type": "done",  "thread_id", "answer", "plan", "sources"}  整轮结束
          {"type": "error", "message": str}    中途出错（本回合不入历史）
        """
        # 校验 + 可能的新会话在响应开始前完成，参数错误可返回 HTTP 400/500
        thread_id = self._ensure_thread(thread_id, question)
        config = {"configurable": {"thread_id": thread_id}}
        self.agent  # 预热：缺密钥 / Checkpointer 初始化失败在写响应前就暴露
        hint = _manual_skill_hint(skill)  # 页面手动选中的技能卡 → 当轮 System Prompt 追加指令

        def _generate() -> Iterator[dict]:
            # 让 plan_task / update_plan / remember 等工具知道“现在在哪个会话里执行”
            set_current_thread(thread_id)
            reset_sources()  # 新一轮问答：清空上一轮遗留的数据来源
            agent = self.agent
            # 本次问答的首选渠道：DeepSeek 若在失败冷却期，则 resolve 会自动落到 openai 备用
            provider = resolve_provider()
            # 上下文工程：本轮**只注册用得上的工具**（schema 是工具上下文里最占地方的一块）
            meter = context.Meter(label=str(thread_id))
            subset, meter.notes["tools"] = select_tools_for(str(question or ""))
            llm = build_llm(provider=provider, force=True).bind_tools(subset)
            fallback_used = False  # 同一次问答只自动切换一次渠道，避免来回横跳

            def _round_text(llm_now):
                """跑一轮模型，把过程转成本轮事件流（**逐 chunk 实时产出**，打字机效果的来源）。

                事件形态：
                  {"type": "token",  "content": str}      文本增量，立刻转发给前端
                  {"type": "rewind", "chars": n}          调用失败时撤回本轮已吐出的 n 字
                  {"type": "ai",     "message": AIMsg}    本轮结束，拿到完整消息
                  {"type": "fail",   "error": Exception}  渠道异常，交给上层切备用渠道/上报

                为什么还要 rewind：模型有时会在调工具前先写一句“我先查一下数据”，
                这些过程句按产品口径不展示；流式下已经吐出去了，就由上层按本轮的
                真实去向（工具轮 / 自检不通过要重写 / 渠道失败要重试）决定撤回多少。
                """
                full = None
                streamed = 0
                tool_round = False
                # 逐字输出也不能漏：流式切分会把号码切成两半，交给 sanitize 的增量器处理
                # （push 返回"现在可以安全吐出去"的部分，剩下的悬着等下一块）
                san = sanitize.StreamSanitizer()
                try:
                    for chunk in llm_now.stream(messages):
                        full = chunk if full is None else full + chunk
                        # 这一轮一旦出现工具调用片段就判定为“工具轮”：后面的文字
                        # 属于模型自言自语，不再外发（已发的由上层统一撤回）
                        if getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None):
                            tool_round = True
                        text = _textify(getattr(chunk, "content", None))
                        if text and not tool_round:
                            text = san.push(text)
                            if not text:
                                continue
                            streamed += len(text)
                            yield {"type": "token", "content": text}
                except Exception as exc:
                    if streamed:
                        yield {"type": "rewind", "chars": streamed}
                    yield {"type": "fail", "error": exc}
                    return
                # 收尾：把缓冲里最后一段也脱敏后吐出（这段的下文不会再来了）
                rest = san.flush()
                if rest and not tool_round:
                    streamed += len(rest)
                    yield {"type": "token", "content": rest}
                yield {"type": "ai", "message": full}

            def _consume(llm_now, pending, out: dict):
                """消费一轮事件流并原样转发，结果写回 out：{full, failed, error}。"""
                out.update({"full": None, "failed": False, "error": None})
                for event in _round_text(llm_now):
                    kind = event["type"]
                    if kind == "token":
                        pending.append(event["content"])
                        yield event
                    elif kind == "rewind":
                        yield event
                    elif kind == "ai":
                        out["full"] = event["message"]
                    else:
                        out["failed"] = True
                        out["error"] = event.get("error")

            state = agent.get_state(config)
            history = list((state.values or {}).get("messages") or [])
            # ① 记忆：长会话压成「摘要 + 最近原文」，短会话原样透传（行为与老版本一致）
            history, digest = prepare_history(thread_id, history)

            # ② 规划：复杂任务先拆解成执行计划（含“沿用上一轮未完成计划”）
            plan, plan_events = _prepare_plan(thread_id, question)
            for event in plan_events:
                yield event

            # ← 查询理解（Prompt Engineering）：先把口语提问消歧成结构化意图
            #   ——时间口径落成具体日期、计数说清去重、排序写明字段、"它/这个"补全指代、
            #     歧义与默认假设显式列出，后面取数就不容易跑偏（失败则静默跳过）
            spec = _understand_question(question, history)

            # ← Dynamic Prompt 每轮现渲染：叠加「当前时间 + 早期摘要 + 本轮计划 + 手动指定数据范围 + 查询理解」
            tool_names_for_prompt = [tool.name for tool in subset]
            system_text = build_system_prompt(summary=digest or None,
                                              tools=tool_names_for_prompt)
            system_text += ("\n\n" + hint if hint else "")
            if plan is not None:
                system_text += "\n\n" + _plan_system_hint(plan)
            if spec:
                system_text += "\n\n" + prompting.render(spec)
            # 树状搜索的候选路线与评分（ToT / MCTS）：让模型知道有哪些备选路径可选
            trail = _REASON_TRAIL.pop("last", None)
            if trail is not None and len(trail.events) > 1:
                system_text += "\n\n" + trail.render(limit=3)
            # 上下文度量：把各层占多少记下来（关 CTX 时 Mirror 仍可统计，开销可忽略）
            meter.record_layer("system", system_text)
            meter.record_layer("history", "".join(getattr(m, "content", "") or ""
                                                  for m in (history or [])))
            meter.record_layer("input", str(question or ""))
            human = HumanMessage(content=question)
            messages = [*history, SystemMessage(content=system_text), human]
            persisted = [human]  # 只把“本回合新增”的消息写回 Checkpointer（避免重复）
            answer_parts: list[str] = []
            plan_snapshot = _status_map(plan)
            tool_names: list[str] = []
            # 自检预算：只有“有计划的回合”才做自检，简单问题一次模型调用都不多花
            reflect_left = plan_max_reflect() if (plan is not None and plan_reflect_enabled()) else 0
            # 本轮的反思记忆（Reflexion）：跨多次自检累积，第二次自检会带上第一次的建议
            reflexion = reasoning.Reflexion(getattr(plan, "goal", "") or question)

            try:
                with self._lock:
                    last_call_key: str | None = None  # 死循环检测：连续同工具且参数完全相同
                    repeat_times = 0
                    for _ in range(MAX_STEPS):
                        # 本轮文字**边出边流**：每一小段 token 立刻发给前端（打字机效果）；
                        # 若这一轮最终要调工具，中间那些“我先查一下”的过程句已被 rewind 撤回，
                        # 仍然做到只给结果、不给过程。
                        pending: list[str] = []
                        out: dict = {}
                        yield from _consume(llm, pending, out)
                        if out.get("failed"):
                            # 当前渠道调用失败（欠费/鉴权/超时等）→ 自动切换到备用渠道重试本回合
                            first_error = out.get("error")
                            backup = next(
                                (p for p in PROVIDER_CHAIN if p != provider
                                 and os.getenv(PROVIDER_PRESETS[p]["key_env"])),
                                None,
                            )
                            if backup is None or fallback_used:
                                raise first_error or RuntimeError("模型调用失败")  # 无可切渠道或已切过一次
                            mark_provider_failed(provider)  # 标记失败进冷却，后续请求直接走备用
                            provider, fallback_used = backup, True
                            llm = build_llm(provider=backup, force=True).bind_tools(subset)
                            pending = []
                            out = {}
                            yield from _consume(llm, pending, out)
                            if out.get("failed"):
                                raise out.get("error") or RuntimeError("备用渠道调用失败")

                        full = out.get("full")
                        if full is None:
                            full = AIMessage(content="")  # 极端情况：流里一个 chunk 都没有
                        full = _sanitize_message(full)   # 写回历史/落盘的也应是脱敏文本
                        messages.append(full)

                        tool_calls = getattr(full, "tool_calls", None) or []
                        if not tool_calls:
                            # ④ 终答轮：先让自检器核对「计划是否真的完成」，没完成就补一轮
                            if reflect_left > 0:
                                reflect_left -= 1
                                # Reflexion：带记忆的自检——历史建议会一并带过去，
                                # 避免重复押同一个说法（同一个坑不踩第二次）
                                decision = reflexion.call(
                                    _llm_complete, plan,
                                    answer="".join(pending), tool_names=tool_names,
                                    round_no=plan_max_reflect() - reflect_left,
                                )
                                events, plan_snapshot = _apply_reflection(
                                    plan, decision, thread_id, plan_snapshot
                                )
                                for event in events:
                                    yield event
                                instruction = decision.get("instruction") or ""
                                if decision.get("action") != "finish" and instruction:
                                    # 自检说还没做完：撤回这一版回答，带上意见再走一轮
                                    rewound = sum(len(p) for p in pending)
                                    if rewound:
                                        yield {"type": "rewind", "chars": rewound}
                                        pending = []
                                    # 自检意见只作为一次性提醒注入上下文，不写进历史（界面不会出现假的用户消息）
                                    messages.append(HumanMessage(content=(
                                        "【执行计划自检】" + instruction
                                        + (("\n" + reflexion.render()) if len(reflexion.notes) > 1 else "")
                                        + "\n请继续完成剩余步骤，全部完成后再给出最终结果。"
                                    )))
                                    continue
                            # 终答轮：正文已在流式过程中逐字发过，这里只汇总落盘
                            persisted.append(full)
                            if pending:
                                answer_parts.append("".join(pending))
                            break  # 模型不再要工具 → 本回合结束
                        # 工具轮：本轮流出去的是模型调工具前的过渡句，统一撤回
                        rewound = sum(len(p) for p in pending)
                        if rewound:
                            yield {"type": "rewind", "chars": rewound}
                        persisted.append(full)
                        for call in tool_calls:
                            name = call.get("name", "")
                            yield {"type": "tool", "name": name, "label": tool_label(name)}
                            if name not in tool_names:
                                tool_names.append(name)
                            tool = TOOL_MAP.get(name)
                            # 死循环检测：与上一次完全相同的工具调用连续出现时，在真正执行前拦截
                            key = (
                                f"{name}:"
                                + json.dumps(
                                    call.get("args") or {},
                                    sort_keys=True, ensure_ascii=False, default=str,
                                )
                            )
                            repeat_times = repeat_times + 1 if key == last_call_key else 1
                            last_call_key = key
                            if repeat_times >= MAX_REPEAT_TOOL:
                                raise RuntimeError(
                                    f"模型连续 {MAX_REPEAT_TOOL} 次重复调用工具 {name}（参数完全相同），"
                                    "疑似陷入死循环，已终止；可换一种问法或把任务拆小后再试。"
                                )
                            try:
                                result = tool.invoke(call.get("args") or {}) if tool else f"没有名为 {name} 的工具"
                                ok = bool(tool) and not str(result).startswith("没有名为")
                            except Exception as exc:
                                result = f"调用工具 {name} 失败：{exc}"
                                ok = False
                            # 上下文度量：工具调用质量（失败率 / 同参数重试率）
                            meter.record_tool(name, call.get("args") or {}, ok)
                            meter.record_layer("tool_result", str(result))
                            tool_message = ToolMessage(content=str(result), tool_call_id=call.get("id"))
                            messages.append(tool_message)
                            persisted.append(tool_message)
                        # ③-附 计划进度：本轮工具可能改动了计划（update_plan / plan_task），同步给前端
                        current = get_active_plan(thread_id)
                        if current is not None and current is not plan:
                            plan = current          # 中途换过计划（plan_task 重新制定）
                        if plan is not None:
                            events, plan_snapshot = _plan_events(plan, plan_snapshot)
                            for event in events:
                                yield event
                            if events:
                                persist_plan(thread_id, plan)
                    else:
                        raise RuntimeError(
                            f"工具调用超过 {MAX_STEPS} 轮仍未结束，已终止；"
                            "可尝试把任务拆成更小的几个问题分别提问。"
                        )

                    agent.update_state(config, {"messages": persisted})  # 落盘本回合
            except Exception as exc:
                persist_plan(thread_id, plan)  # 出错也把已有的计划进度留下来（便于重试）
                yield {"type": "error", "message": str(exc)}
                return

            answer = sanitize.mask_text("".join(answer_parts))
            meter.record_layer("output", answer)          # 上下文度量：本轮最终产出
            meter.notes["prompt_report"] = build_system_prompt.last_report or {}
            context.persist(meter.summary())              # CTX_STATS=1 时落盘，供跨版本对比
            # ⑤ 落盘：计划进度 + 本轮数据来源 → 会话元数据；消息历史已在上面写回 Checkpointer
            persist_plan(thread_id, plan)
            round_sources = take_sources()          # 本轮真正用到的数据出处（工具侧登记）
            messages_now = self.history(thread_id)
            patch = {"updated_at": _now(), "message_count": len(messages_now), "sources": round_sources}
            info = self.store.get(thread_id) or {}
            if not info.get("title") or info.get("title") == DEFAULT_TITLE:
                patch["title"] = make_title(question) or DEFAULT_TITLE
            self.store.update(thread_id, **patch)
            if round_sources:
                yield {"type": "sources", "items": round_sources}
            yield {
                "type": "done",
                "thread_id": thread_id,
                "answer": answer,
                "plan": plan.to_dict() if plan is not None else None,
                "sources": round_sources,
            }

        return _generate()

    def stream_deep(self, thread_id: str | None, question: str) -> Iterator[dict]:
        """深度搜索（Deep Research 式）：拆子问题 → 多轮智能检索 → 查漏补缺 → 带引用综合回答。

        事件流与 stream_ask 兼容（token / done / error 同名），并额外产出
        plan / search / gap / rerank / sources 等“研究过程”事件供前端展示；
        结束前把「提问 + 综合回答」追加进当前会话的 Checkpointer，历史与消息数保持一致。
        """
        thread_id = self._ensure_thread(thread_id, question)
        config = {"configurable": {"thread_id": thread_id}}
        self.agent  # 预热：缺密钥/初始化错误在写响应前暴露

        def _generate() -> Iterator[dict]:
            set_current_thread(thread_id)
            reset_sources()  # 新一轮深度搜索：清空上一轮遗留的数据来源
            agent = self.agent
            answer = ""
            sources: list[dict] = []
            try:
                with self._lock:
                    for event in _iter_deep_search(question):
                        event_type = event.get("type")
                        if event_type == "answer":
                            answer = event.get("answer") or ""
                            sources = event.get("sources") or []
                        elif event_type == "error":
                            yield event  # 出错回合不入历史（与 stream_ask 一致）
                            return
                        yield event
                    if answer:
                        agent.update_state(
                            config,
                            {"messages": [HumanMessage(content=question), AIMessage(content=answer)]},
                        )
            except Exception as exc:
                yield {"type": "error", "message": str(exc)}
                return

            messages_now = self.history(thread_id)
            # 深度搜索的 sources 是知识库证据片段，同样落盘，刷新页面还能看到出处
            patch = {"updated_at": _now(), "message_count": len(messages_now), "sources": sources}
            info = self.store.get(thread_id) or {}
            if not info.get("title") or info.get("title") == DEFAULT_TITLE:
                patch["title"] = make_title(question) or DEFAULT_TITLE
            self.store.update(thread_id, **patch)
            yield {"type": "done", "thread_id": thread_id, "answer": answer, "sources": sources}

        return _generate()


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #
def run_query(agent, question: str, thread_id: str = "default") -> str:
    """兼容旧用法：在指定线程中执行问答并保留该线程的历史上下文。"""
    result = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        {"configurable": {"thread_id": thread_id}, "recursion_limit": 200},
    )
    return last_ai_message(result.get("messages", [])) or str(result["messages"][-1].content)


def _demo(service: ChatService) -> None:
    """演示两层存储：

    1. Checkpointer（会话内记忆）：会话 A/B 互不可见；
    2. LangGraph Store（跨会话长期记忆）：A 里明确“记住”后，B 也能查到。
    """
    a = service.new_conversation("会话 A：记录个人信息")
    b = service.new_conversation("会话 B：空白会话")

    info = provider_info()
    _, backend = get_store()
    print(
        f"服务商：{info['provider']} · 模型：{info['model']} · "
        f"Checkpointer：{service.backend} · Store：{backend}\n"
    )
    steps = [
        (a["id"], "你好，我叫小明，我最喜欢的数字是 7。", "① 会话 A 普通聊天（未要求记住，不应写入长期记忆）"),
        (b["id"], "我叫什么名字？我最喜欢的数字是几？", "② 会话 B 提问 —— 会话隔离，应该答不上来"),
        (a["id"], "记住：我叫小明，最喜欢的数字是 7。", "③ 会话 A 明确要求记住 —— remember 写入跨会话 Store"),
        (b["id"], "我叫什么名字？我最喜欢的数字是几？", "④ 会话 B 再提问 —— Store 跨会话共享，应该答得上来"),
    ]
    for thread_id, question, note in steps:
        print(f"{note}")
        reply = service.ask(thread_id, question)["answer"]
        print(f"[{thread_id}] 问：{question}")
        print(f"[{thread_id}] 答：{reply}\n")

    print("会话列表：")
    for item in service.list_conversations():
        print(f"  - {item['id']}  {item['title']}  ({item['message_count']} 条消息)")
    print("\nStore 长期记忆：")
    memories = list_memories()
    if not memories:
        print("  （空）")
    for item in memories:
        print(f"  - {item['content']}（记于 {item['created_at']}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="多会话 LangChain Agent（Checkpointer 记忆）")
    parser.add_argument("question", nargs="*", help="要问的问题；留空则运行多会话 demo")
    parser.add_argument("--thread", help="指定会话 thread_id，默认临时会话")
    parser.add_argument("--new", action="store_true", help="新建一个会话并打印 thread_id")
    parser.add_argument("--list", action="store_true", help="列出所有会话")
    parser.add_argument("--history", metavar="THREAD_ID", help="打印某会话的历史")
    parser.add_argument("--rename", nargs=2, metavar=("THREAD_ID", "TITLE"), help="重命名会话")
    parser.add_argument("--delete", metavar="THREAD_ID", help="删除会话")
    parser.add_argument("--stream", action="store_true", help="流式打印回答（打字机效果，配合问题使用）")
    parser.add_argument("--deep", action="store_true",
                        help="深度搜索（拆子问题→多轮检索→查漏补缺→带引用综合回答），需要知识库与 LLM")
    parser.add_argument("--provider", choices=sorted(PROVIDER_PRESETS), help="临时指定服务商（覆盖 LLM_PROVIDER）")
    parser.add_argument("--plan", choices=("auto", "always", "off"),
                        help="规划模式：auto=复杂任务自动规划（默认）/ always=每次都先规划 / off=关闭规划")
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.plan:
        os.environ["PLAN_MODE"] = args.plan

    service = ChatService()

    if args.new:
        print(service.new_conversation()["id"])
        return
    if args.list:
        for item in service.list_conversations():
            print(f"{item['id']}\t{item['title']}\t{item['message_count']} 条\t更新于 {item['updated_at']}")
        return
    if args.history:
        for msg in service.history(args.history):
            print(f"{'你' if msg['role'] == 'user' else 'AI'}：{msg['content']}")
        return
    if args.rename:
        service.rename_conversation(*args.rename)
        print("已重命名")
        return
    if args.delete:
        service.delete_conversation(args.delete)
        print("已删除")
        return

    if args.question:
        question = " ".join(args.question)
        thread_id = args.thread or service.new_conversation()["id"]
        if args.deep:
            print(f"[thread={thread_id}] 深度搜索：{question}", flush=True)
            pending = ""
            for event in service.stream_deep(thread_id, question):
                event_type = event["type"]
                if event_type == "info":
                    print(f"[知识库] {event['message']} · 引擎：{event.get('backend', '')}", flush=True)
                elif event_type == "plan":
                    print("[检索计划] " + "  |  ".join(event["queries"]), flush=True)
                elif event_type == "search":
                    print(f"  检索(第{event['round']}轮)「{event['query']}」命中 {event['hits']} 段 [{event.get('engines', '')}]", flush=True)
                elif event_type == "gap":
                    print("[查漏补缺] " + "  |  ".join(event["queries"]), flush=True)
                elif event_type == "rerank":
                    print(f"[LLM 重排] 综合前对 {event['count']} 个候选按相关度重排", flush=True)
                elif event_type == "token":
                    pending += event["content"]
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        sys.stdout.write(line + "\n")
                        sys.stdout.flush()
                elif event_type == "sources":
                    print("\n\n[参考来源]")
                    for item in event["items"]:
                        loc = f"第{item['chunk_index']}段"
                        if item.get("page"):
                            loc += f" · PDF 第{item['page']}页"
                        print(f"  [{item['index']}] {item['source']} · {loc}（相关度{item.get('score', '?')}）")
                    print("", flush=True)
                elif event_type == "error":
                    print(f"\n出错了：{event['message']}", flush=True)
                elif event_type == "done":
                    if pending:
                        sys.stdout.write(pending)
                        sys.stdout.flush()
                        pending = ""
                    print("\n[done]")
            if pending:
                sys.stdout.write(pending + "\n")
                sys.stdout.flush()
            return
        if args.stream:
            print(f"[thread={thread_id}] ", end="", flush=True)
            for event in service.stream_ask(thread_id, question):
                if event["type"] == "token":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "thinking":
                    print(f"[规划] {event.get('message', '')}", flush=True)
                elif event["type"] == "plan":
                    print(f"\n[执行计划] {event.get('goal', '')}", flush=True)
                    for step in event.get("steps", []):
                        print(f"   {step['id']}. {step['title']}", flush=True)
                elif event["type"] == "plan_step":
                    step = event["step"]
                    print(f"   → 第{step['id']}步 {step['status_label']}：{step['title']}", flush=True)
                elif event["type"] == "tool":
                    print(f"\n⏳ [调用工具：{event['name']}] ", flush=True)
                elif event["type"] == "error":
                    print(f"\n出错了：{event['message']}", flush=True)
                elif event["type"] == "done":
                    print("\n[done]")
            return
        reply = service.ask(thread_id, question)
        print(f"[thread={reply['thread_id']}] {reply['answer']}")
        return

    _demo(service)


if __name__ == "__main__":
    main()
