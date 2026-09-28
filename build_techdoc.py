"""生成《九天梧桐 AI 工作台》技术文档 PDF。

用法::

    python build_techdoc.py                      # 输出到 ../九天梧桐AI工作台技术文档.pdf
    python build_techdoc.py -o docs/tech.pdf     # 指定输出路径

为什么不是 markdown 直转：中文排版（CJK 折行、表格换行、书签与页码）需要可控；
而且工具清单、评测分数、向量库规模这类数据**直接从代码里读**，
保证文档跟代码同步——手写文档写完就过时。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

# --------------------------------------------------------------------------- #
# 字体：中文必须显式注册 TTF，否则全是黑块
# --------------------------------------------------------------------------- #
FONTS = Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("CN", str(FONTS / "msyh.ttc"), subfontIndex=0))
pdfmetrics.registerFont(TTFont("CN-B", str(FONTS / "msyhbd.ttc"), subfontIndex=0))
pdfmetrics.registerFontFamily("CN", normal="CN", bold="CN-B", italic="CN", boldItalic="CN-B")

INK = colors.HexColor("#1f2430")
ACCENT = colors.HexColor("#2f6fed")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d8dce6")
CODE_BG = colors.HexColor("#f4f6fa")
HEAD_BG = colors.HexColor("#2f6fed")
ROW_ALT = colors.HexColor("#f6f8fc")


def st(name, **kw) -> ParagraphStyle:
    base = dict(fontName="CN", fontSize=10.2, leading=16.2, textColor=INK, wordWrap="CJK")
    base.update(kw)
    return ParagraphStyle(name, **base)


S_TITLE = st("title", fontName="CN-B", fontSize=24, leading=32, alignment=TA_CENTER,
             textColor=ACCENT)
S_SUB = st("sub", fontSize=11.5, leading=19, alignment=TA_CENTER, textColor=MUTED)
S_H1 = st("h1", fontName="CN-B", fontSize=15.5, leading=23, spaceBefore=2, spaceAfter=8,
          textColor=ACCENT)
S_H2 = st("h2", fontName="CN-B", fontSize=11.8, leading=18, spaceBefore=10, spaceAfter=5)
S_H3 = st("h3", fontName="CN-B", fontSize=10.4, leading=16, spaceBefore=7, spaceAfter=3)
S_BODY = st("body", spaceAfter=5)
S_NOTE = st("note", fontSize=9, leading=14, textColor=MUTED, spaceAfter=5)
S_BULLET = st("bullet", spaceAfter=2.5, leftIndent=11, bulletIndent=1)
S_CODE = st("code", fontSize=8.1, leading=12.2)
S_TH = st("th", fontName="CN-B", fontSize=8.9, leading=12.8, textColor=colors.white)
S_TD = st("td", fontSize=8.9, leading=12.8)
S_SM = st("sm", fontSize=8.1, leading=11.8)
S_TOC0 = st("toc0", fontName="CN-B", fontSize=9.8, leading=17)
S_TOC1 = st("toc1", fontSize=9.2, leading=15.4, leftIndent=14, textColor=MUTED)

DOC_TITLE = "九天梧桐 AI 工作台 · 技术文档"


def esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, s=S_BODY):
    return Paragraph(str(text), s)


def H1(text):
    return Paragraph(esc(text), S_H1)


def H2(text):
    return Paragraph(esc(text), S_H2)


def H3(text):
    return Paragraph(esc(text), S_H3)


def B(items, s=S_BULLET):
    return [Paragraph(esc(i), s, bulletText="·") for i in items]


def code(text: str) -> Table:
    """代码块：浅底方框，逐行转义后用 <br/> 换行（Preformatted 不折行会溢出页面）。"""
    lines = [esc(line).replace(" ", "&nbsp;") for line in str(text).strip("\n").split("\n")]
    body = Paragraph("<br/>".join(lines) or "&nbsp;", S_CODE)
    table = Table([[body]], colWidths=[165 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def table(rows, widths, style_s=None, header=True, align_right=()):
    """统一外观的表格：表头深蓝，正文斑马纹；单元格一律包 Paragraph 以便中文折行。"""
    data = []
    for r_i, row in enumerate(rows):
        line = []
        for c_i, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                line.append(cell)
            elif header and r_i == 0:
                line.append(Paragraph(esc(cell), S_TH))
            elif c_i in align_right:
                line.append(Paragraph(esc(cell), S_TD))
            else:
                line.append(Paragraph(esc(cell), S_TD))
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    base = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        base += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG)]
        for i in range(1, len(data)):
            if i % 2 == 0:
                base.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(base + (style_s or [])))
    return t


class TechDoc(BaseDocTemplate):
    """带页眉页脚/页码的模板，并把标题写进 PDF 书签大纲。"""

    def __init__(self, filename, outline, **kw):
        BaseDocTemplate.__init__(self, filename, pagesize=A4, leftMargin=20 * mm,
                                 rightMargin=18 * mm, topMargin=20 * mm,
                                 bottomMargin=17 * mm, title=DOC_TITLE,
                                 author="九天梧桐 AI 工作台", subject="技术实现说明", **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      id="body", leftPadding=0, rightPadding=0, topPadding=0,
                      bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame]),
            PageTemplate(id="body", frames=[frame], onPage=self._decorate),
        ])
        self.outline = outline

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ("h1", "h2"):
            level = 0 if flowable.style.name == "h1" else 1
            self.outline.append((level, flowable.getPlainText(), self.page))
            key = f"sec{len(self.outline)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=level)

    def _decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("CN", 8)
        canvas.setFillColor(MUTED)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, A4[1] - 14 * mm, A4[0] - doc.rightMargin, A4[1] - 14 * mm)
        canvas.drawString(doc.leftMargin, A4[1] - 12.2 * mm, DOC_TITLE)
        canvas.drawRightString(A4[0] - doc.rightMargin, A4[1] - 12.2 * mm, dt.date.today().isoformat())
        canvas.line(doc.leftMargin, 12.5 * mm, A4[0] - doc.rightMargin, 12.5 * mm)
        canvas.drawCentredString(A4[0] / 2, 8.6 * mm, f"第 {doc.page} 页")
        canvas.restoreState()


# --------------------------------------------------------------------------- #
# 从代码里读动态事实（失败就用占位，保证文档仍能生成）
# --------------------------------------------------------------------------- #
def collect_facts() -> dict:
    facts: dict = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    # ① 工具清单 + 所属分组
    try:
        from core import agent
        from core.cognition import context
        group_of: dict[str, str] = {}
        for group, names in dict(context.TOOL_GROUPS).items():
            for name in names:
                group_of.setdefault(name, group)
        for name in list(context.CORE_TOOLS):
            group_of.setdefault(name, "core")
        rows = []
        for tool in agent.TOOLS:
            desc = (tool.description or "").strip().splitlines()
            brief = (desc[0] if desc else "").strip()
            # 工具描述里常带 markdown 记号（**强调**、`code`），PDF 里会原样印出来
            brief = re.sub(r"[*`]", "", brief)
            brief = brief[:58] + ("…" if len(brief) > 58 else "")
            rows.append((tool.name, brief, group_of.get(tool.name, "-")))
        facts["tools"] = rows
    except Exception as exc:                       # 依赖缺失时不影响文档生成
        facts["tools"] = []
        facts["tool_error"] = f"{type(exc).__name__}: {exc}"

    # ② 向量库规模
    try:
        from services.knowledge import vectordb
        stats = vectordb.get_store().stats()
        facts["vdb"] = stats
    except Exception as exc:
        facts["vdb"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ③ 知识库文件数
    try:
        files = [p for p in (APP_ROOT / "knowledge").rglob("*") if p.is_file()]
        facts["kb_files"] = len(files)
        facts["kb_bytes"] = sum(p.stat().st_size for p in files)
    except Exception:
        facts["kb_files"] = 0
        facts["kb_bytes"] = 0

    # ④ 评测成绩
    try:
        data = json.loads((APP_ROOT / "eval" / "accuracy_last.json").read_text(encoding="utf-8"))
        facts["acc"] = {"total": data.get("total"), "passed": data.get("passed"),
                        "accuracy": data.get("accuracy"), "by": data.get("by_category", {})}
    except Exception:
        facts["acc"] = None

    # ⑤ 代码规模
    try:
        counts = {}
        for folder in ("core", "services", "eval"):
            total, n = 0, 0
            for path in (APP_ROOT / folder).rglob("*.py"):
                if "__pycache__" in str(path):
                    continue
                total += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
                n += 1
            counts[folder] = (n, total)
        counts["root"] = (1, len((APP_ROOT / "web.py").read_text(encoding="utf-8",
                                                                 errors="ignore").splitlines()))
        facts["code"] = counts
    except Exception:
        facts["code"] = {}

    return facts


F = collect_facts()


# --------------------------------------------------------------------------- #
# 正文
# --------------------------------------------------------------------------- #
CHAPTERS = [
    "1 项目概述",
    "2 快速开始（安装 / 配置 / 启动）",
    "3 系统架构与一次问答的完整链路",
    "4 模块清单与目录结构",
    "5 LLM 层：多服务商、渠道容错",
    "6 工具系统：26 个能力与分组注册",
    "7 推理与规划：CoT / ToT / MCTS / Reflexion",
    "8 三级数据能力",
    "9 上下文工程",
    "10 向量数据库与知识库检索",
    "11 记忆、脱敏与非结构化表格库",
    "12 HTTP 接口与前端交互",
    "13 配置说明（环境变量）",
    "14 评测体系与实测成绩",
    "15 安全边界与隐私说明",
    "16 附录：扩展开发与常见问题",
]


def cover_block():
    acc = F.get("acc") or {}
    lines = [
        Spacer(1, 58 * mm),
        Paragraph(DOC_TITLE, S_TITLE),
        Spacer(1, 5 * mm),
        Paragraph("Agent 架构 · 三级数据能力 · 上下文工程 · 向量检索 · 评测体系", S_SUB),
        Spacer(1, 16 * mm),
    ]
    meta = [
        ["文档版本", "v2.0"],
        ["生成时间", F["generated"]],
        ["适用对象", "二次开发者 / 部署运维 / 技术评审"],
        ["工具数量", f"{len(F['tools'])} 个（动态读取 core/agent.py）"],
        ["问答准确率", (f"{acc.get('passed')}/{acc.get('total')} = "
                     f"{acc.get('accuracy'):.1%}") if acc else "见第 14 章"],
    ]
    lines.append(table(meta, [40 * mm, 90 * mm], header=False,
                       style_s=[("BACKGROUND", (0, 0), (0, -1), CODE_BG)]))
    lines += [Spacer(1, 12 * mm),
              P("本PDF 由 <b>build_techdoc.py</b> 自动生成：工具清单、向量库规模、评测成绩"
                "均从代码与报告中实时读取，内容随项目演进同步。", S_NOTE)]
    return lines


def toc_block(entries):
    rows = [["", ""]]
    for item, page in entries:
        level = 0 if not item.startswith("    ") else 1
        style_s = S_TOC0 if level == 0 else S_TOC1
        rows.append([Paragraph(esc(item.strip()), style_s),
                     Paragraph(str(page or ""), S_TOC1)])
    t = Table(rows, colWidths=[148 * mm, 20 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return [Paragraph("目录", S_H1), t]


def body_blocks():
    s: list = []
    add = s.append

    # ---------------- 1 项目概述 ----------------
    add(H1("1 项目概述"))
    add(P("九天梧桐 AI 工作台是一个面向企业数据场景的 <b>Agent 应用</b>：用户用自然语言提问，"
          "系统自动判断该查业务库、查知识库、还是直接计算/建模，调用相应工具后组织成回答，"
          "并把用到的数据来源完整地展示出来。"))
    add(P("它不是单纯的聊天机器人，而是把「LLM + Planning + Tool use + Memory」"
          "四种能力落到具体模块上的一个可用系统："))
    tool_rows = [["能力", "落在哪", "说明"]]
    tool_rows += [
        ["LLM", "core/llm.py,core/agent.py", "统一封装多家兼容 OpenAI 协议的服务商，带失败冷却与自动切换"],
        ["Planning", "core/planning.py", "任务是否复杂判断、执行计划生成与按步推进、终答前自检"],
        ["Tool use", "core/agent.py", "26 个工具，手写 ReAct 循环，带死循环检测与轮次上限"],
        ["Memory", "Checkpointer + LangGraph Store", "短期：会话检查点；长期：跨会话事实；压缩：早期对话摘要"],
        ["Reasoning", "core/reasoning.py", "CoT 思维链、ToT 树状多路径、MCTS 规划搜索、Reflexion 反思记忆"],
        ["Context", "core/context.py", "系统提示分层合成、工具动态注册、检索上下文管线、上下文度量"],
        ["Retrieval", "services/rag.py + services/vectordb.py", "多路召回 RRF 融合，向量持久化到 SQLite 并可建 ANN 索引"],
    ]
    add(table(tool_rows, [24 * mm, 46 * mm, 98 * mm]))
    add(Spacer(1, 3 * mm))
    add(P("界面为单页 Web（index.html + web.py），流式逐字输出，右侧可查看执行计划、"
          "数据来源详情抽屉、图画产物等。"))

    # ---------------- 2 快速开始 ----------------
    add(H1("2 快速开始（安装 / 配置 / 启动）"))
    add(H2("2.1 安装依赖"))
    add(code("cd app\npython -m venv .venv\n.venv\\Scripts\\activate        # macOS/Linux: source .venv/bin/activate\n"
             "pip install -r requirements.txt"))
    add(H2("2.2 配置"))
    add(P("复制 <b>.env.example</b> 为 <b>.env</b>，至少配置一家模型服务商："))
    add(code("LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=sk-xxxxxxxx\nDEEPSEEK_BASE_URL=https://api.deepseek.com\n"
             "LLM_MODEL=deepseek-chat"))
    add(P("业务库（MySQL）连接信息在 .env 的 MYSQL_* 段；非结构化表格库、SQLite 数据目录等"
          "均可通过环境变量覆盖，完整清单见第 13 章。"))
    add(H2("2.3 启动"))
    add(code("python web.py                # 默认 http://127.0.0.1:5000\n"
             "python web.py --port 8080    # 指定端口（HOST / PORT 环境变量亦可）"))
    add(P("命令行模式（不走 Web）：", S_NOTE))
    add(code("from core.agent import ChatService\nservice = ChatService()\n"
             "conv = service.new_conversation(\"临时会话\")\n"
             "print(service.ask(conv[\"id\"], \"医疗库上个月收入多少\")[\"answer\"])"))

    # ---------------- 3 架构 ----------------
    add(PageBreak())
    add(H1("3 系统架构与一次问答的完整链路"))
    add(H2("3.1 分层结构"))
    add(code(
        "index.html（前端：流式渲染 / 计划面板 / 来源抽屉）\n"
        "        |  NDJSON 事件流\n"
        "web.py（Flask：会话、流式问答、知识管理、静态图）\n"
        "        |\n"
        "core/agent.py（ChatService：手写 ReAct 循环 + 工具调度 + 计划推进 + 反思自检）\n"
        "  |-- core/planning.py    计划生成、推进、自检\n"
        "  |-- core/reasoning.py   CoT / ToT / MCTS / Reflexion\n"
        "  |-- core/prompting.py   查询意图结构化、必查清单\n"
        "  |-- core/context.py     上下文分层合成、工具选择、检索管线、度量\n"
        "  |-- core/llm.py         多服务商、渠道冷却与自动切换\n"
        "  |\n"
        "  |-- services/rag.py        知识库检索（多路召回 RRF）\n"
        "  |-- services/vectordb.py   持久化向量库（SQLite + ANN）\n"
        "  |-- services/sanitize.py   输出脱敏\n"
        "  |-- services/ml_forecast.py 时序预测\n"
        "  |-- services/ml_insight.py  统计分析 / 异常检测 / 聚类\n"
        "  |-- services/pysandbox.py   受限 Python 沙箱\n"
        "  |-- skills/                 技能卡（口径说明）"))
    add(H2("3.2 一次提问发生了什么"))
    add(P("以「医疗库上个月收入多少，顺便说明口径」为例："))
    steps = [
        "路由：判断是「问数」还是「问制度」，按任务阶段挑选本轮注册的工具子集（context.select_tools）。",
        "计划：复杂任务经 ToT 或 MCTS 搜索出候选路线，选评分最高的生成执行计划；简单任务跳过。",
        "提示合成：把时间、角色、安全清单、示例、计划、工具指引等块按优先级合成 System Prompt。",
        "执行：ReAct 循环——模型选工具 -> 执行 -> 结果回灌 -> 再决策，含渠道失败切换与死循环检测。",
        "取数：先查技能卡确认口径，再写 SQL；必要时用 run_python 做二次计算。",
        "自检：终答前 Reflexion 检查是否覆盖了问题，未覆盖则撤回重试（同一建议重复出现会加重提醒）。",
        "产出：流式输出正文，登记数据来源，必要时脱敏后落库返回给前端。",
    ]
    s.extend(B(steps))

    # ---------------- 4 模块清单 ----------------
    add(PageBreak())
    add(H1("4 模块清单与目录结构"))
    rows = [["文件", "职责"]]
    rows += [
        ["web.py", "Flask 服务：会话 CRUD、流式问答 NDJSON、知识库管理、静态图、健康检查"],
        ["core/llm.py", "多家 OpenAI 兼容服务商统一封装；失败冷却、自动切渠道"],
        ["core/agent.py", "工具定义与注册、手写 ReAct 循环、记忆压缩、计划推进、脱敏出口"],
        ["core/planning.py", "needs_plan 复杂度判断、make_plan、Plan 状态机、update_plan、reflect"],
        ["core/reasoning.py", "COT_RULES、cot_think、tot_search、mcts_search、Reflexion、Trail"],
        ["core/prompting.py", "QuerySpec 查询意图结构化、两份必查清单、工具正反例"],
        ["core/context.py", "提示分层合成 compose、工具选择 select_tools、检索管线、Meter 度量"],
        ["services/rag.py", "文档加载与分块、多路召回、RRF 融合、来源标注、重排"],
        ["services/vectordb.py", "SQLite 持久化向量库：local/api 向量化、IVF 索引、CRUD、sync"],
        ["services/sanitize.py", "按列名 + 文本正则两路脱敏；结果集、回答文本统一出口"],
        ["services/ml_forecast.py", "月度指标时序预测：多模型选优 + 递归滚动"],
        ["services/ml_insight.py", "统计画像、相关矩阵、异常检测、聚类分群"],
        ["services/pysandbox.py", "受限 Python 沙箱：静态检查 + 循环插桩预算"],
        ["eval/qa_cases.py", "50 题标准答案数据集（真值 SQL 实时执行）"],
        ["eval/eval_accuracy.py", "问答准确率评测 harness：执行、判分、报告"],
        ["eval/eval_context.py", "上下文四维评估：完成率 / 效率 / 调用质量 / 一致性"],
        ["index.html", "单页前端：流式打字、计划面板、来源抽屉、深浅主题"],
    ]
    add(table(rows, [42 * mm, 126 * mm]))
    add(Spacer(1, 3 * mm))
    code_info = F.get("code") or {}
    if code_info:
        size_rows = [["目录", "文件数", "代码行数"]]
        label = {"core": "app/core", "services": "app/services", "eval": "app/eval",
                 "root": "app/web.py"}
        for key in ("core", "services", "eval", "root"):
            if key in code_info:
                n, lines = code_info[key]
                size_rows.append([label[key], str(n), f"{lines:,}"])
        add(table(size_rows, [50 * mm, 40 * mm, 40 * mm]))

    # ---------------- 5 LLM ----------------
    add(PageBreak())
    add(H1("5 LLM 层：多服务商、渠道容错"))
    add(P("core/llm.py 把各家 OpenAI 兼容接口统一成一个 build_llm(provider)："
          "切换服务商只要改环境变量，业务代码不用动。"))
    rows = [["机制", "说明"]]
    rows += [
        ["多服务商", "deepseek / openai / moonshot / 通义等，配置段独立，互不影响"],
        ["失败冷却", "某渠道连续报错后进入冷却期，期间自动走备用渠道；冷却结束自动恢复"],
        ["单次只切一次", "同一次问答最多自动切换一次渠道，避免来回横跳导致重试抖动"],
        ["Thinking 过滤", "<think>...</think> 这类思考段会被滤掉，不进正文也不进历史"],
        ["超时与重试", "按 LLM_TIMEOUT 控制单次调用上限；失败后按配置重试"],
    ]
    add(table(rows, [30 * mm, 138 * mm]))

    # ---------------- 6 工具系统 ----------------
    add(PageBreak())
    add(H1("6 工具系统：26 个能力与分组注册"))
    add(P("工具不是越多越好：全部注册时模型要消化大量 schema，还容易「选择困难」。"
          "因此默认按任务阶段动态注册子集（第 9 章），核心工具常驻不裁。"))
    add(H2("6.1 工具全表（实时读取）"))
    if F["tools"]:
        group_cn = {"core": "核心（常驻）", "sql": "业务库 SQL", "tables": "非结构化表格库",
                    "knowledge": "知识库", "post": "后处理（画图/计算）",
                    "analysis": "分析与建模", "forecast": "预测"}
        rows = [["工具名", "用途（摘要）", "分组"]]
        for name, brief, group in F["tools"]:
            rows.append([name, brief, group_cn.get(group, group)])
        add(table(rows, [40 * mm, 100 * mm, 28 * mm]))
    else:
        add(P("（未能加载工具清单：%s）" % F.get("tool_error", "未知原因"), S_NOTE))
    add(H2("6.2 循环保护"))
    s.extend(B([
        "最大轮次上限：超过即终止并给出已有结论，避免无限调用。",
        "死循环检测：同一工具同一参数重复调用会被识别并打断。",
        "空参修复：模型漏传必需参数时按工具 schema 补齐后再调用。",
        "每次调用都计入 Meter（core/context.Meter），用于评测工具调用质量。",
    ]))

    # ---------------- 7 推理与规划 ----------------
    add(PageBreak())
    add(H1("7 推理与规划：CoT / ToT / MCTS / Reflexion"))
    add(P("在既有 ReAct 循环与 Plan-and-Execute 之上，core/reasoning.py 补的是"
          "「多条候选之间择优」与「把失败经验攒下来」。"))
    add(code(
        "                      ┌─ CoT：事实 / 推断 / 动作 / 校验 四拍节拍（纯文本，零调用）\n"
        "用户提问 → 复杂度判断 ┤\n"
        "                      └─ 复杂任务 ─┬─ ToT  逐层展开多条路线 → 自评打分 → beam 剪枝\n"
        "                                   └─ MCTS UCB1 选择 → 扩展 → 模拟评分 → 反向传播\n"
        "                                              ↓\n"
        "                                       最优计划 → ReAct 执行 → Reflexion 终答自检"))
    rows = [["能力", "实现方式", "成本 / 触发时机"]]
    rows += [
        ["Plan-and-Execute", "planning.needs_plan 判断复杂度 -> make_plan -> Plan 状态机 -> update_plan", "复杂任务即可，调用少"],
        ["CoT", "COT_RULES 静态注入四拍节拍；cot_think 可显式推理一次", "节拍零调用；显式推理按需开启"],
        ["ToT", "每层生成 K 条实质不同的路线 -> LLM 自评打分 -> 保留 top ⌈K/2⌉ -> 下一层细化", "约 3~5 次调用，REASON_MODE=tot/auto"],
        ["MCTS", "UCB1 选择 -> 扩展候选下一步 -> 模拟评分 -> 反向传播（价值累加、逐层衰减）", "MCTS_ITERS 默认 4 轮"],
        ["Reflexion", "自检建议入账；下一轮带上历史；重复建议加重提醒并沉淀成「经验教训」", "复用既有自检轮次，不额外加调用"],
    ]
    add(table(rows, [26 * mm, 86 * mm, 56 * mm]))
    add(Spacer(1, 2 * mm))
    add(P("树搜索的候选路线与评分会渲染成「推理路径」注入提示词，让用户/模型知道还有哪些备选:"
          "例如「候选『先核对口径再聚合』评分 9.2；候选『直接聚合』评分 6.1」。"
          "任何环节失败都静默降级为单条计划或不规划，绝不打断对话。"))

    # ---------------- 8 三级数据能力 ----------------
    add(PageBreak())
    add(H1("8 三级数据能力"))
    rows = [["级别", "能力", "工具 / 模块", "说明"]]
    rows += [
        ["初级", "SQL 查询", "execute_sql、query_tables", "三业务库只读 SQL；非结构化表格走 SQLite"],
        ["初级", "Python 计算", "run_python -> services/pysandbox.py", "最近一次查询结果注入为 rows / cols，写 Python 做二次计算"],
        ["中级", "统计分析 · 关联 · 公式", "analyze_data -> services/ml_insight.py", "统计画像（均值/四分位/偏度/缺失率）+ Pearson & Spearman 相关矩阵与解读"],
        ["中级", "口径对齐", "get_db_skill、analyze_query、QuerySpec", "技能卡给出默认口径；查询意图结构化纠正术语与错别字"],
        ["高级", "时序预测", "forecast_metric -> ml_forecast.py", "多模型选优 + 递归滚动预测"],
        ["高级", "异常检测", "detect_data_anomalies", "z-score(3σ) + 箱线图(1.5IQR) + 孤立森林三口径投票，≥2 票才算异常"],
        ["高级", "聚类挖掘", "cluster_data", "标准化后用轮廓系数自动定簇，输出每簇画像并自动命名"],
    ]
    add(table(rows, [15 * mm, 34 * mm, 48 * mm, 71 * mm]))
    add(H2("8.1 run_python 沙箱的防线"))
    s.extend(B([
        "允许：四则与比较、列表/字典推导、安全内置函数、math / statistics / numpy、print。",
        "禁止：import、open、eval/exec/getattr/globals、下划线属性、while 循环（静态阶段拦截）。",
        "防跑飞：给每个循环体插桩计数，超过 50 万次迭代直接中止——线程 join 超时杀不死线程，"
        "while True 会一直占满一个核，所以不用它当防线。",
        "脱敏：数据在进沙箱之前先按列名脱一遍，模型怎么写代码都吐不出个人信息。",
    ]))
    add(H2("8.2 统计列的自动甄别"))
    add(P("analyze_data / cluster_data 不会把 client_id 算成「均值 400.5」：按列名像 ID/编码/状态位、"
          "整数且取值几乎不重复、只有两种整数取值三条判据排除，并在结果里说明原因；"
          "带小数的列一律视为度量放行，避免误杀 total_assets 这类高基数业务量。"))

    # ---------------- 9 上下文工程 ----------------
    add(PageBreak())
    add(H1("9 上下文工程"))
    add(P("五层上下文（系统提示 / 工具定义 / 历史 / 检索 / 用户输入）被当成可测量、可裁剪的对象："))
    rows = [["层", "做法", "关键实现"]]
    rows += [
        ["系统提示", "每块带优先级，跨块按行指纹去重，超预算从低优先级的可选块开始丢",
         "PRIORITY、compose()、CTX_BUDGET"],
        ["工具定义", "按任务阶段注册子集，一行一个工具说明（含参数约束）",
         "TOOL_GROUPS、CORE_TOOLS、TOOL_BRIEF、select_tools_for()"],
        ["历史", "长会话压缩为早期摘要注入，细节不确定时要求向用户确认",
         "摘要 Checkpointer + 记忆压缩"],
        ["检索", "查询改写 -> 扩大候选池 -> 覆盖率重排 -> 同源限流 -> 相关性阈值 -> 来源标注 -> 段落裁剪",
         "rewrite_query、rerank_by_coverage、diversify、build_retrieved_context"],
        ["用户输入", "查询意图结构化（QuerySpec），纠正术语并给出默认口径",
         "prompting.understand"],
    ]
    add(table(rows, [18 * mm, 88 * mm, 62 * mm]))
    add(H2("9.1 系统提示的优先级"))
    add(P("时间(0) < 安全清单(10) < 角色(20) < 任务计划(30) < 示例(40) < 记忆(50) < 提示(60)；"
          "必留块标记 optional=False，超预算时只丢低优先级的可选块；"
          "合成报告留在 build_system_prompt.last_report，能看清本次去了多少重复行、丢了哪些块。"))
    add(H2("9.2 为什么要有「查询词覆盖率重排」"))
    add(P("知识库里文档块数极不均衡（实测政策文档 5 块 vs SQL 问答示例 1000+ 块），"
          "只按融合排名取 Top-K 时，大文档靠「金额」「超过」这类高频词把真正命中的小文档挤到第 4 位，"
          "结果三条里没有一条政策原文。补上覆盖率这一维后：命中查询里更多不同词元的片段更靠前，"
          "政策片段从第 4 位提到第 1 位，且不影响其余问法。"))

    # ---------------- 10 向量库与检索 ----------------
    add(PageBreak())
    add(H1("10 向量数据库与知识库检索"))
    add(P("改造前的「向量检索」是进程启动时一次性算完的内存列表：不落盘、无增量、无索引、重启即失效。"
          "services/vectordb.py 把它做成了真正的库："))
    add(code(
        "                 ┌─ local：字级 + bigram 哈希 TF-IDF（离线、零依赖、可复现）\n"
        " 分块文本 → 向量化 ┤\n"
        "                 └─ api  ：OpenAI 兼容 /embeddings（配 EMBEDDING_BASE_URL 后自动切换）\n"
        "                                    ↓\n"
        "                        SQLite 落盘（ref / text / meta / dim / backend / float32 BLOB）\n"
        "                                    ↓\n"
        "                     内存索引：IDF 重算 → 小规模精确余弦，超过阈值建 IVF 倒排索引\n"
        "                     （KMeans 粗量化 + nprobe 只搜最近若干簇，候选不足自动回退）"))
    vdb = F.get("vdb") or {}
    rows = [["维度", "实现"]]
    rows += [
        ["持久化", "SQLite 落盘 app/data/vector.sqlite3，重启直接加载，无需额外服务"],
        ["两种后端", "local（默认，离线哈希 TF-IDF）与 api（真语义 embedding）"],
        ["ANN 索引", "低于阈值走精确余弦；超过自动建 IVF；候选不足自动回退，保证不漏召回"],
        ["IDF 处理", "库里存不含 IDF 的原始 TF 向量，加载时按当前语料重算，增量入库不会让旧向量失真"],
        ["操作", "upsert / upsert_many / sync / search / delete / prune / clear / stats，全程 RLock"],
        ["元数据过滤", "where 支持字典（等值 / 枚举）或自定义谓词"],
        ["增量同步", "sync 按「ref + 文本 + 维度/后端一致」跳过未变动；prune 清理已删除文档"],
        ["一致性保护", "换后端或改维度会明确报错，而不是给出错误的相似度"],
    ]
    add(table(rows, [24 * mm, 144 * mm]))
    add(Spacer(1, 2 * mm))
    if "vectors" in vdb:
        add(P("当前库况：向量 <b>%s</b> 条，维度 <b>%s</b>，后端 <b>%s</b>，IVF 索引 <b>%s</b>，"
              "体积 <b>%s MB</b>；知识库文档 <b>%s</b> 个（共 %.1f KB）。"
              % (vdb.get("vectors"), vdb.get("dim"), vdb.get("backend"),
                 "已启用" if vdb.get("ivf") else "未启用", vdb.get("size_mb"),
                 F.get("kb_files", 0), (F.get("kb_bytes", 0) or 0) / 1024)))
    add(H2("10.1 检索链路"))
    s.extend(B([
        "多路召回：关键词（BM25 风格）+ 向量，用 RRF 融合；可用 RAG_RERANK 开启 LLM 重排。",
        "查询改写：先洗掉寒暄与口水词，再进检索（口语残留会直接拉低相似度）。",
        "同源限流 + 覆盖率重排：见 9.2，避免大文档刷榜。",
        "相关性阈值：低于 CTX_MIN_SCORE 的片段不进上下文；全部低于阈值时明确告知「证据不足」，"
        "而不是硬凑内容让模型编。",
        "来源标注：路径 / 段落 / PDF 页码 / 更新时间 / 相关度随结果一起给出。",
    ]))

    # ---------------- 11 记忆 / 脱敏 / 表格库 ----------------
    add(PageBreak())
    add(H1("11 记忆、脱敏与非结构化表格库"))
    add(H2("11.1 三层记忆"))
    rows = [["层", "载体", "作用"]]
    rows += [
        ["短期", "Checkpointer（SqliteSaver，缺依赖降级 MemorySaver）", "按 thread_id 存会话检查点，天然隔离"],
        ["长期", "LangGraph Store", "跨会话的事实记忆（如用户偏好），可按关键词检索"],
        ["压缩", "早期对话摘要", "长会话把早期内容压缩成摘要注入系统提示，避免上下文爆炸"],
    ]
    add(table(rows, [16 * mm, 64 * mm, 88 * mm]))
    add(H2("11.2 输出脱敏"))
    add(P("services/sanitize.py 走两条路：<b>按列名</b>（patient_name / birth_date 这类列名直接判定）与"
          "<b>文本正则</b>（带称谓的人名：患者张三）。四个新工具的结果也统一过脱敏："
          "run_python 在数据源头脱、异常检测的标签列按真实列名脱。"
          "实测姓名与生日会被遮，而「公费医疗 / 商业保险」这类枚举值不误伤。"))
    add(H2("11.3 非结构化表格库"))
    add(P("把 Excel / CSV / HTML 表格等解析进本地 SQLite，然后让 Agent 用和查 MySQL 一样的方式查："
          "先「分析表结构」再「召回相关表」最后写只读 SQL，配合技能卡给出口径；"
          "命令行也能在不调用模型的情况下做解析和查询。"))

    # ---------------- 12 接口与前端 ----------------
    add(PageBreak())
    add(H1("12 HTTP 接口与前端交互"))
    rows = [["方法", "路径", "说明"]]
    rows += [
        ["GET", "/api/health", "健康检查：Checkpointer 后端、知识库、数据库、长期记忆、planning、tables 规模等"],
        ["GET", "/api/conversations", "会话列表（按更新时间倒序）"],
        ["POST", "/api/conversations", "新建会话，body 可选 { \"title\": \"...\" }"],
        ["GET", "/api/conversations/<id>/messages", "完整历史 + 最近执行计划 plan + 最近数据来源 sources"],
        ["PATCH", "/api/conversations/<id>", "重命名会话"],
        ["DELETE", "/api/conversations/<id>", "删除会话并清理该线程所有检查点"],
        ["DELETE", "/api/conversations", "一键清空全部会话（跨会话长期记忆保留），返回 { \"cleared\": n }"],
        ["GET", "/api/memory", "列出跨会话长期记忆；带 ?q=关键词 时按相关度检索"],
        ["DELETE", "/api/memory/<key>", "删除某条长期记忆"],
        ["GET", "/api/skills", "可手动选择的数据查询技能卡（key / 中文名 / 就绪状态）"],
        ["POST", "/api/chat", "流式问答，返回 NDJSON 事件流"],
        ["POST", "/api/deep_search", "深度搜索（多步检索 + 引用标注）"],
    ]
    add(table(rows, [16 * mm, 52 * mm, 100 * mm]))
    add(H2("12.1 /api/chat 的事件流"))
    add(P("每行一个 JSON 事件（Content-Type: application/x-ndjson），依次可能出现："))
    add(code(
        "{\"type\": \"thinking\",  \"message\": \"正在制定执行计划\"}\n"
        "{\"type\": \"plan\",      \"goal\": \"...\", \"steps\": [...], \"progress\": {...}}\n"
        "{\"type\": \"plan_step\", \"step\": {\"id\": 2, \"title\": \"...\", \"status\": \"done\"}}\n"
        "{\"type\": \"token\",     \"content\": \"字增量\"}      # 真正流式，逐 chunk\n"
        "{\"type\": \"rewind\",    \"chars\": 6}                # 撤回已吐出的过渡句\n"
        "{\"type\": \"tool\",      \"name\": \"execute_sql\"}\n"
        "{\"type\": \"sources\",   \"items\": [{\"kind\": \"database\", \"label\": \"...\", \"rows\": 12}]}\n"
        "{\"type\": \"done\",      \"thread_id\": \"...\", \"answer\": \"...\", \"plan\": {...}}\n"
        "{\"type\": \"error\",     \"message\": \"...\"}"))
    s.extend(B([
        "事件协议向后兼容：简单问题不会有 plan / sources，前端忽略不认识的事件类型即可。",
        "前端还提供了「来源详情抽屉」：点击任一出处卡片，右侧滑出类型徽章、基本信息、涉及数据表、",
        "说明与原文摘录、完整 SQL，遮罩 / × / Esc 均可关闭。",
    ]))

    # ---------------- 13 配置 ----------------
    add(PageBreak())
    add(H1("13 配置说明（环境变量）"))
    rows = [["变量", "默认值", "作用"]]
    rows += [
        ["LLM_PROVIDER / *_API_KEY / *_BASE_URL", "deepseek", "模型服务商、密钥与端点；LLM_MODEL 指定模型名"],
        ["LLM_TIMEOUT / LLM_MAX_RETRIES", "视实现", "单次调用超时与重试次数"],
        ["MYSQL_HOST / PORT / USER / PASSWORD", "-", "业务库连接；三个库：金融 / 医疗 / 通信"],
        ["RAG_TOP_K / RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP", "3 / 500 / 60", "知识库召回条数与分块参数"],
        ["VECTOR_DB / VECTOR_DB_PATH", "1 / app/data/vector.sqlite3", "是否启用持久化向量库及其路径"],
        ["VECTOR_BACKEND / VECTOR_DIM", "auto / 512", "local 或 api；local 哈希向量的维度"],
        ["VECTOR_IVF_MIN / VECTOR_NPROBE", "5000 / 8", "超过多少条建 IVF 索引；每次探测几个簇"],
        ["REASON_MODE / REASON_COT", "auto / 1", "auto 只在复杂任务上树搜索；cot 为是否注入思维链节拍"],
        ["TOT_BREADTH / TOT_DEPTH", "3 / 2", "ToT 每层候选路线数与层数"],
        ["MCTS_ITERS / MCTS_MAX_STEPS", "4 / 6", "MCTS 迭代次数与生成计划的最大步数"],
        ["CTX / CTX_BUDGET", "1 / 12000", "上下文工程总开关与系统提示字符预算"],
        ["CTX_TOOL_SELECT / CTX_SNIPPET", "1 / 800", "是否动态注册工具子集；单个检索片段的字符上限"],
        ["CTX_MIN_SCORE / CTX_STATS", "0.15 / 0", "检索相关性阈值；是否落盘上下文度量"],
        ["PLAN_* / PLAN_MAX_REFLECT", "视实现", "规划总开关、最大步数、自检轮次"],
        ["SANDBOX_TIMEOUT / SANDBOX_MAX_STEPS", "3 / 500000", "沙箱单次上限与循环迭代预算"],
        ["TABLE_ENABLED / 表格库相关", "视实现", "非结构化表格库开关与解析目录"],
    ]
    add(table(rows, [50 * mm, 34 * mm, 84 * mm]))
    add(P("把 CTX=0 可一键回到改造前的行为（纯拼接 + 全量工具），方便做 A/B 对照。", S_NOTE))

    # ---------------- 14 评测 ----------------
    add(PageBreak())
    add(H1("14 评测体系与实测成绩"))
    add(H2("14.1 问答准确率（任务完成率）"))
    add(P("eval/qa_cases.py 提供 50 道题，标准答案<b>全部由真实数据源算出</b>——"
          "SQL 题在库里执行 truth_sql 取单值，知识题按政策原文匹配，诚实性题用正则判是否承认查不到。"
          "eval/eval_accuracy.py 自动执行、判分、出报告。"))
    acc = F.get("acc")
    if acc:
        rows = [["类别", "通过 / 总数", "正确率"]]
        for key, value in sorted(acc.get("by", {}).items()):
            # 报告里题目总数的字段名是 n，不是 total（按 n 取，避免印出 None）
            rows.append([key, f"{value.get('passed')} / {value.get('n')}",
                         f"{value.get('accuracy', 0):.1%}"])
        rows.append(["合计", f"{acc.get('passed')} / {acc.get('total')}",
                     f"{acc.get('accuracy', 0):.1%}"])
        add(table(rows, [50 * mm, 46 * mm, 40 * mm]))
    add(code("python eval/eval_accuracy.py                  # 全量 50 题，约 4 分钟\n"
             "python eval/eval_accuracy.py --limit 6        # 快跑\n"
             "python eval/eval_accuracy.py --json eval/accuracy_last.json"))
    add(H2("14.2 上下文四维评估"))
    add(P("eval/eval_context.py 评估四个维度，指标不达标会以非零退出码结束，可直接接 CI："))
    rows = [["维度", "评估方式"]]
    rows += [
        ["任务完成率", "迷你测试集：精简工具集后，完成该任务必需的工具是否还在"],
        ["上下文效率", "统计各层字符 / token，与全量注入对比省了多少"],
        ["工具调用质量", "Meter 统计失败率与「成功后重复同样调用」的浪费率（失败后重试视为纠偏，不算问题）"],
        ["响应一致性", "同一输入连跑多次，工具集与提示必须逐字节一致"],
    ]
    add(table(rows, [30 * mm, 138 * mm]))
    add(H2("14.3 优化过程中真实修掉的问题"))
    rows = [["现象", "根因", "修法"]]
    rows += [
        ["知识类题目一度只有 22%", "知识问法没命中路由关键词 -> 落到 SQL 组 -> search_knowledge 没注册",
         "知识库文档动态抽取关键词 + 默认组兜底 + 提示里加「问数还是问制度」路由规则"],
        ["政策片段被大文档挤出 Top-K", "大文档靠高频词刷榜，政策排队到第 4",
         "查询词覆盖率重排 + 同源限流 + 候选池扩大"],
        ["个别 SQL 题时好时坏", "题目口径含糊（算不算已取消/正常/已成），两边都有依据",
         "每题口径写死，必要时拆成两题"],
        ["「表不存在」答对却判错", "判分依赖固定关键词连写",
         "文本题支持正则判分"],
    ]
    add(table(rows, [40 * mm, 56 * mm, 72 * mm]))

    # ---------------- 15 安全 ----------------
    add(PageBreak())
    add(H1("15 安全边界与隐私说明"))
    s.extend(B([
        "SQL 只读：业务库工具限制为只读语句，禁止写操作；非结构化表格库同样是只读 SQLite。",
        "Python 沙箱是给自家 Agent 用的护栏（静态检查禁用危险调用 + 循环预算），"
        "不是多租户安全边界，真隔离要靠容器。",
        "输出脱敏：姓名、生日、证件号、电话等在进模型上下文前后分别处理，压缩泄漏面。",
        "召回不硬凑：知识库证据不足时明确说「没查到」，避免用常识填空造成误导。",
        "密钥只在 .env 中配置，文档与代码中不出现明文密钥；.env 不应入库。",
    ]))

    # ---------------- 16 附录 ----------------
    add(H1("16 附录：扩展开发与常见问题"))
    add(H2("16.1 添加自定义工具"))
    add(code("from langchain_core.tools import tool\n\n"
             "@tool\ndef my_tool(param: str) -> str:\n"
             "    \"\"\"一句话说明用途，再写参数使用场景与限制（这行会进工具指引）。\"\"\"\n"
             "    return \"结果\"\n\n"
             "# 在 core/agent.py 里加入 TOOLS 列表，并在 TOOL_BRIEF / TOOL_GROUPS 中登记，\n"
             "# 否则动态注册时它可能被裁掉，且提示里也没有它的一句话说明。"))
    add(H2("16.2 常见问题"))
    rows = [["现象", "排查 / 处理"]]
    rows += [
        ["答非所问或乱猜", "先看知识库是否命中：命中不足会返回「证据不足」。必要时放宽 CTX_MIN_SCORE 或补充文档"],
        ["感觉变慢", "REASON_MODE=react 或 TOT_DEPTH=1 关闭树搜索；CTX=0 可做 A/B 对照"],
        ["向量库报维度/后端不一致", "换过 VECTOR_BACKEND 或 VECTOR_DIM 后需 python -m services.knowledge.rag --rebuild 重建"],
        ["工具明明写了却没被调用", "检查是否已登记 TOOL_BRIEF / TOOL_GROUPS，动态注册会裁掉未登记的工具"],
        ["改了代码没生效", "Python 侧改动需重启 python web.py；纯前端改动刷新页面即可"],
        ["想拿到一次性完整结果", "用 ChatService.ask()，或把 NDJSON 里的 token 事件拼接起来"],
    ]
    add(table(rows, [46 * mm, 122 * mm]))
    add(Spacer(1, 6 * mm))
    add(P("文档由 build_techdoc.py 生成（reportlab + 微软雅黑）。"
          "工具清单、向量库规模、评测成绩在生成时实时读取，重跑即可得到与最新代码一致的文档。",
          S_NOTE))
    return s


def build_story(toc_entries=None):
    story: list = []
    story.extend(cover_block())
    story.append(PageBreak())
    story.extend(toc_block(toc_entries or [(c, None) for c in CHAPTERS]))
    story.append(PageBreak())
    story.extend(body_blocks())
    return story


def main() -> int:
    parser = argparse.ArgumentParser(description="生成项目技术文档 PDF")
    parser.add_argument("-o", "--out", default=str(APP_ROOT.parent / "九天梧桐AI工作台技术文档.pdf"))
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 两遍构建：第一遍拿到真实页码，第二遍渲染目录（目录行数固定，页码才稳定）
    tmp = out.with_suffix(".toc.tmp.pdf")
    outline: list = []
    TechDoc(str(tmp), outline).build(build_story())
    toc_entries = [(("    " if level else "") + text, page) for level, text, page in outline]
    TechDoc(str(out), outline=[]).build(build_story(toc_entries))
    tmp.unlink(missing_ok=True)

    size_kb = out.stat().st_size / 1024
    print(f"已生成：{out}")
    print(f"大小：{size_kb:.0f} KB ｜ 章节 {len([o for o in outline if o[0] == 0])} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
