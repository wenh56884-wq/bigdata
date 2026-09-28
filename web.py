"""Flask Web 服务：为多会话（多重对话）Agent 提供 HTTP 接口（/api/chat 为流式 NDJSON）。"""

import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, Response, jsonify, request, send_from_directory

from core.agent import ChatService, db_skill_cards, delete_memory, list_memories, search_memories
from services import hitl, debugging

app = Flask(__name__)
# 上传大小上限（要略大于单文件上限，留给 multipart 的开销）
app.config["MAX_CONTENT_LENGTH"] = int(
    float(os.getenv("UPLOAD_MAX_MB", "1024")) * 1024 * 1024 * 1.2)
service = ChatService()


def _json_payload() -> dict:
    """Return a JSON object without raising on missing/invalid content type."""
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@app.get("/")
def index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, **service.info()})


@app.get("/api/skills")
def skill_list():
    """列出可手动选择的数据查询技能卡（库 key + 中文名 + 就绪状态），供前端下拉选择。"""
    return jsonify({"skills": db_skill_cards()})


@app.get("/reports/<path:filename>")
def reports_file(filename):
    """供网页展示 reports/ 目录下的图表 PNG（只放行顶层 *.png，防目录穿越）。"""
    name = Path(filename).name
    if name != filename or not re.fullmatch(r"[A-Za-z0-9_\-]+\.png", name):
        return jsonify({"error": "资源不存在"}), 404
    target = PROJECT_ROOT / "reports" / name
    if not target.is_file():
        return jsonify({"error": "资源不存在"}), 404
    resp = send_from_directory(PROJECT_ROOT / "reports", name)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# --------------------------- 会话（thread）管理 --------------------------- #
@app.get("/api/conversations")
def list_conversations():
    return jsonify({"conversations": service.list_conversations()})


@app.post("/api/conversations")
def create_conversation():
    title = (_json_payload().get("title") or "").strip()
    return jsonify({"conversation": service.new_conversation(title or None)}), 201


@app.get("/api/conversations/<thread_id>/messages")
def conversation_messages(thread_id):
    """会话完整历史 + 最近的执行计划（plan），便于刷新页面后仍能看到计划进度。"""
    item = service.store.get(thread_id)
    if not item:
        return jsonify({"error": "会话不存在。"}), 404
    return jsonify({
        "thread_id": thread_id,
        "messages": service.history(thread_id),
        "plan": item.get("plan"),
        "sources": item.get("sources") or [],   # 最近一轮的数据来源，界面在回答下方展示
    })


@app.patch("/api/conversations/<thread_id>")
def rename_conversation(thread_id):
    title = (_json_payload().get("title") or "").strip()
    if not title:
        return jsonify({"error": "标题不能为空。"}), 400
    item = service.rename_conversation(thread_id, title)
    if not item:
        return jsonify({"error": "会话不存在。"}), 404
    return jsonify({"conversation": item})


@app.delete("/api/conversations")
def clear_conversations():
    """一键清空全部会话（元数据 + Checkpointer 里的对话历史；跨会话长期记忆保留）。"""
    return jsonify({"cleared": service.clear_conversations()})


@app.delete("/api/conversations/<thread_id>")
def delete_conversation(thread_id):
    item = service.delete_conversation(thread_id)
    if not item:
        return jsonify({"error": "会话不存在。"}), 404
    return jsonify({"deleted": thread_id})


# ----------------------- 跨会话长期记忆（Store）----------------------- #
@app.get("/api/memory")
def memory_list():
    """列出全局共享 Store 里的跨会话记忆。

    可选参数 q：按相关度检索（如 /api/memory?q=报销 标准）；不传则返回最近的若干条。
    """
    query = (request.args.get("q") or "").strip()
    if query:
        limit = request.args.get("limit", type=int) or 8
        return jsonify({"query": query, "memories": search_memories(query, limit=max(1, min(limit, 50)))})
    return jsonify({"memories": list_memories()})


@app.delete("/api/memory/<key>")
def memory_delete(key):
    delete_memory(key)
    return jsonify({"deleted": key})


@app.post("/api/approvals/<approval_id>")
def approval_decide(approval_id):
    """批准、拒绝或编辑一条正在等待的 Agent 高风险操作。"""
    payload = _json_payload()
    try:
        result = hitl.manager.resolve(
            approval_id,
            payload.get("decision") or "",
            payload.get("message") or "",
            payload.get("args"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if result is None:
        return jsonify({"error": "审批不存在、已处理或已超时。"}), 404
    return jsonify({"approval": result})


# -------------------- 管理员上传：统一目录 + 落盘即解析 -------------------- #
@app.get("/api/uploads")
def upload_list():
    """列出统一上传目录（data/uploads）里的文件。"""
    try:
        from services import table_memory, uploads
        return jsonify({
            "directory": str(uploads.directory()),
            "files": uploads.list_files(),
            "memory": table_memory.summary(),
        })
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_list")), 500


@app.post("/api/uploads")
def upload_create():
    """管理员上传表格文件：存进统一目录 → **立即解析 → 写记忆 → 重建索引**。

    multipart/form-data，字段名 file（可多文件重复该字段）。
    若配置了 ADMIN_TOKEN，则需附带 ?token=xxx 或 X-Admin-Token 头。
    """
    token = (os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        given = (request.args.get("token") or request.headers.get("X-Admin-Token") or "").strip()
        if given != token:
            return jsonify({"error": "需要管理员令牌。"}), 401
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "没有收到文件（字段名应为 file）。"}), 400
    try:
        from services import uploads
        saved, failed = [], []
        for item in files:
            try:
                saved.append(uploads.save(item.filename or "", item.read()))
            except Exception as exc:
                failed.append({"name": item.filename, "error": str(exc)})
        return jsonify({"saved": saved, "failed": failed}), 201
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_create")), 500


@app.get("/api/uploads/<path:name>/preview")
def upload_preview(name):
    """查看上传后的实际内容：表格行列、文档正文或图片 OCR 文本。"""
    try:
        from services import uploads
        return jsonify(uploads.preview(name))
    except FileNotFoundError:
        return jsonify({"error": "文件不存在。"}), 404
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_preview")), 500


@app.get("/api/uploads/<path:name>/content")
def upload_image_content(name):
    """仅以内联方式返回已上传图片，供资料预览弹窗展示原图。"""
    try:
        from services import uploads
        target = uploads.image_file(name)
        if not target:
            return jsonify({"error": "图片不存在。"}), 404
        response = send_from_directory(uploads.directory(), target.name)
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_content")), 500


@app.delete("/api/uploads/<path:name>")
def upload_delete(name):
    """删除上传的文件（连带清记忆、重建索引）。"""
    token = (os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        given = (request.args.get("token") or request.headers.get("X-Admin-Token") or "").strip()
        if given != token:
            return jsonify({"error": "需要管理员令牌。"}), 401
    try:
        from services import uploads
        if not uploads.delete(name):
            return jsonify({"error": "文件不存在。"}), 404
        return jsonify({"deleted": name})
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_delete")), 500


@app.get("/api/uploads/memory")
def upload_memory():
    """查看表格自动记忆（数据卡片 + 问答经验）的概况，便于管理员确认「学到了什么」。"""
    try:
        from services import table_memory
        return jsonify(table_memory.summary())
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="upload_memory")), 500


@app.delete("/api/uploads/memory")
def upload_memory_clear():
    token = (os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        given = (request.args.get("token") or request.headers.get("X-Admin-Token") or "").strip()
        if given != token:
            return jsonify({"error": "需要管理员令牌。"}), 401
    from services import table_memory
    table_memory.clear()
    return jsonify({"cleared": True})


# ------------------------------ 对话问答 ------------------------------ #
@app.post("/api/chat")
def chat():
    """流式问答：响应体为 NDJSON，每行一个事件（UTF-8）：

        {"type": "thinking",  "message": "..."}   过程提示（如“正在制定执行计划”）
        {"type": "plan",      "goal", "steps", "progress"}      本轮执行计划（复杂任务才有）
        {"type": "plan_step", "step": {...}}       计划某一步的状态变化（进度条）
        {"type": "token", "content": "字增量"}     前端逐字拼成完整回答
        {"type": "tool",  "name": "calculator"}    模型开始调用某工具
        {"type": "approval_required", ...}            高风险工具暂停，等待人工批准/拒绝
        {"type": "done",  "thread_id", "answer", "plan"}        本轮结束
        {"type": "error", "message": "...", "error_id": "..."}  中途出错（本回合不入历史）

    前端对不认识的事件类型直接忽略即可，老版本页面不会因为多出 plan 事件而报错。
    """
    payload = _json_payload()
    question = (payload.get("question") or "").strip()
    thread_id = (payload.get("thread_id") or "").strip() or None
    skill = (payload.get("skill") or "").strip()  # 前端手动指定的数据技能卡；空串=自动识别

    # stream_ask() 在返回生成器前完成校验与 Agent 预热，
    # 参数/配置错误在此以正常状态码返回，而不是中途断流
    try:
        events = service.stream_ask(thread_id, question, skill=skill)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="chat")), 500

    def generate():
        for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/deep")
def deep_search():
    """深度搜索（Deep Research 式）：拆子问题 → 多轮检索 → 查漏补缺 → 带引用综合回答。

    与 /api/chat 同款的 NDJSON 流，额外会先产出研究过程事件：
        {"type": "info",    ...}                            深度搜索开始 / 引擎情况
        {"type": "plan",    "queries": ["子查询1", ...]}    子问题拆解
        {"type": "search",  "query": ..., "hits": n, "engines": ..., "round": 1|2}
        {"type": "gap",     "queries": [...]}                查漏补缺（可无）
        {"type": "rerank",  "count": n}                      LLM 相关度重排（可无）
        {"type": "token",   "content": "..."}                综合回答正文增量
        {"type": "sources", "items": [{index/source/chunk/page/score}]}
        {"type": "done",    "thread_id": ..., "answer": ..., "sources": [...]}
    """
    payload = _json_payload()
    question = (payload.get("question") or "").strip()
    thread_id = (payload.get("thread_id") or "").strip() or None

    try:
        events = service.stream_deep(thread_id, question)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify(debugging.error_payload(exc, context="deep")), 500

    def generate():
        for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -------------------- API 路径的统一 JSON 错误兜底 --------------------
# 为什么要有：前端把响应当 JSON 解析，Flask 默认的 404/413/500 是 HTML 错误页，
# 前端会报「Unexpected token '<'」这种让人摸不着头脑的错。兜底成 JSON 后，
# 前端能直接把原因（旧进程没重启 / 文件超限 / 服务内部错误）说清楚。
def _json_error(status: int, message: str):
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), status
    return None                      # 非 API 路径走 Flask 默认错误页


@app.errorhandler(404)
def _not_found(_e):
    hit = _json_error(404, "接口不存在。若刚更新过代码，请重启 python web.py。")
    return hit if hit is not None else _e


@app.errorhandler(405)
def _bad_method(_e):
    hit = _json_error(405, "请求方法不对（该路径不支持此方法）。")
    return hit if hit is not None else _e


@app.errorhandler(413)
def _too_large(_e):
    limit = app.config.get("MAX_CONTENT_LENGTH", 0)
    hint = f"（上限约 {limit / 1024 / 1024:.0f} MB，可用 UPLOAD_MAX_MB 调整）" if limit else ""
    hit = _json_error(413, f"上传内容超过大小上限{hint}。")
    return hit if hit is not None else _e


@app.errorhandler(500)
def _server_error(_e):
    if request.path.startswith("/api/"):
        return jsonify(debugging.error_payload(_e, context="flask_500")), 500
    return _e


if __name__ == "__main__":
    import socket
    import threading
    import time
    import webbrowser

    host = os.getenv("HOST", "127.0.0.1")
    try:
        port = int(os.getenv("PORT", "5000"))
    except (TypeError, ValueError):
        port = 5000
    if not 1 <= port <= 65535:
        port = 5000

    def open_browser_when_ready() -> None:
        """轮询直到服务端口可连接，再打开浏览器，避免服务未就绪时页面报“无法访问”。"""
        url = f"http://{host}:{port}"
        for _ in range(100):  # 最多等待 30 秒
            with socket.socket() as probe:
                if probe.connect_ex((host, port)) == 0:
                    print(f"[九天梧桐] 服务已就绪，正在打开浏览器：{url}", flush=True)
                    webbrowser.open(url)
                    return
            time.sleep(0.3)
        print(f"[九天梧桐] 服务迟迟未就绪，未自动打开浏览器，请手动访问：{url}", flush=True)

    # NO_BROWSER=1 可跳过自动打开；调试重载模式下只在真正监听端口的子进程里开
    if os.getenv("NO_BROWSER") != "1" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Thread(target=open_browser_when_ready, daemon=True).start()

    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
