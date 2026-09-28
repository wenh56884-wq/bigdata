# -*- coding: utf-8 -*-
"""受限 Python 计算沙箱：给 Agent 一个「用 Python 算」的能力。

为什么要有这一层
----------------
业务数据里有大量 SQL 不好写、写起来又慢又容易错的活：同比环比、移动平均、分位数、
线性回归斜率、同比天数对齐、多个结果集之间的四则运算、字符串清洗……
让模型把这些交给我们这条语言不可避免地危险，所以这里做的是**受限子集**：

    ✅ 允许：四则运算、math / statistics / numpy、列表字典推导、
             内置的安全函数（len/sum/sorted/round/…）、print 输出
    ❌ 禁止：import、文件读写、网络、属性访问以 `_` 开头（拿不到 `().__class__` 链路）、
             eval/exec/compile/open/getattr/globals/input 等危险名字

另外给了一个**软超时**：沙箱跑在 daemon 线程里，超过 SANDBOX_TIMEOUT 秒（默认 3s）
直接丢弃这次结果（死循环写不出来可用的答案，但也不会拖挂服务）。

定位（重要）：这是给自家 Agent 用的**护栏**，不是多租户安全边界；
取值范围是「模型由我们的 System Prompt 约束生成的短代码」。真正的隔离要靠容器。

自检：python services/pysandbox.py
"""

from __future__ import annotations

import ast
import io
import math
import statistics
import threading
from typing import Any

try:
    import numpy as np
except Exception:                       # numpy 缺失时降级为纯 Python（功能略减但仍可用）
    np = None


TIMEOUT_SECONDS = 3.0
MAX_CODE_CHARS = 2000
MAX_OUTPUT_CHARS = 2000
MAX_LIST_ITEMS = 50
# 循环总迭代预算：插桩计数超过它就直接抛 SandboxTimeout。
# 注意：线程 join 超时**杀不死**线程（`while True` 会一直吃满一个核），
# 所以真正的防线是这里——禁止 while + 给每个循环体注入步数计数。
MAX_LOOP_STEPS = 500_000

# ---- 可用内置（白名单：没列出的名字在沙箱里根本不存在） ----
SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float, "frozenset": frozenset,
    "int": int, "isinstance": isinstance, "len": len, "list": list, "map": map,
    "max": max, "min": min, "pow": pow, "range": range, "reversed": reversed,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "zip": zip, "True": True, "False": False, "None": None, "print": print,
    "Exception": Exception, "ValueError": ValueError, "ZeroDivisionError": ZeroDivisionError,
}

FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "import_module", "__import__", "breakpoint",
    "memoryview", "object", "super", "classmethod", "staticmethod", "property",
}


class SandboxError(Exception):
    """代码没通过静态检查（不是运行时错误）。"""


class SandboxTimeout(Exception):
    """循环迭代超出预算（等价于「这段代码跑不完」）。"""


class _Budget(ast.NodeTransformer):
    """给每个循环体插一行 `_tick()`：迭代累计超预算就抛 SandboxTimeout。

    为什么要这一步：Python 没法安全地中断一个正在跑的线程，
    thread.join(timeout) 只是主线程不再等，里面的死循环照样吃满 CPU。
    """

    def visit_While(self, node: ast.While):            # 一律禁用：模型写 while 基本意味着想要「跑到某个条件」
        raise SandboxError("不允许 while 循环（请用 for + range/list，并保证能在有限步内结束）")

    def visit_For(self, node: ast.For):
        tick = ast.Expr(value=ast.Call(
            func=ast.Name(id="_tick", ctx=ast.Load()), args=[], keywords=[]))
        self.generic_visit(node)
        node.body.insert(0, tick)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.generic_visit(node)                      # 函数体内的循环同样会被插桩
        return node


def check_code(code: str) -> ast.Module:
    """静态检查 + 插桩：不合规则直接抛 SandboxError（在真正执行之前拦住）。

    检查项：长度 → 语法 → import → while → 双下划线属性 → 危险名字；
    通过后给循环体注入步数计数，得到一棵「跑不完会自己停下来」的语法树。
    """
    if not code or not code.strip():
        raise SandboxError("代码为空")
    code = code.strip()
    if len(code) > MAX_CODE_CHARS:
        raise SandboxError(f"代码过长（上限 {MAX_CODE_CHARS} 字符）")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"语法错误：{exc.msg}（第 {exc.lineno} 行）")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("不允许 import（只能用已内置的 math / statistics / numpy）")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SandboxError(f"不允许访问下划线属性 .{node.attr}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise SandboxError(f"不允许使用 {node.id}()")
        if isinstance(node, (ast.Lambda,)):
            continue
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                if isinstance(deco, ast.Name) and deco.id.startswith("_"):
                    raise SandboxError("不允许的装饰器")
    tree = _Budget().visit(tree)
    ast.fix_missing_locations(tree)
    return tree


def _safe_namespace(extra: dict[str, Any] | None = None,
                    budget: int = MAX_LOOP_STEPS) -> dict[str, Any]:
    counter = {"steps": 0}

    def _tick() -> None:
        counter["steps"] += 1
        if counter["steps"] > budget:
            raise SandboxTimeout(f"循环迭代超过 {budget:,} 次，已中止（请缩小数据范围或改写写法）")

    ns: dict[str, Any] = {
        "__builtins__": dict(SAFE_BUILTINS),
        "math": math,
        "statistics": statistics,
        "_tick": _tick,
    }
    if np is not None:
        ns["np"] = np
    if extra:
        ns.update(extra)
    return ns


def fmt(value: Any, limit: int = MAX_LIST_ITEMS) -> str:
    """把结果渲染成给模型看的字符串（长列表截断、浮点收敛到可读精度）。"""
    text = _render(value, limit)
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "…（结果过长已截断）"


def _render(value: Any, limit: int) -> str:
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if value is None or isinstance(value, (int, bool, str)):
        return str(value)
    if np is not None and isinstance(value, np.generic):
        return _render(value.item(), limit)
    if np is not None and isinstance(value, np.ndarray):
        return _render(value.tolist(), limit)
    if isinstance(value, dict):
        if len(value) > limit:
            head = list(value.items())[:limit]
            body = ", ".join(f"{_render(k, 5)}: {_render(v, 5)}" for k, v in head)
            return "{" + body + f", …共 {len(value)} 项}}"
        return "{" + ", ".join(f"{_render(k, 5)}: {_render(v, 5)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:limit]
        tail = f"，…共 {len(value)} 项" if len(value) > limit else ""
        inner = ", ".join(_render(v, 5) for v in items)
        return ("[" + inner + "]" if isinstance(value, list)
                else "(" + inner + ")" if isinstance(value, tuple) else "{" + inner + "}") + tail
    return str(value)


def run(code: str, extra: dict[str, Any] | None = None,
        timeout: float | None = None) -> dict[str, Any]:
    """执行一段受限 Python，返回 {ok, result, result_text, stdout, error}。

    - 约定：把结果赋给 `result` 变量；没有的话取**最后一行表达式**的值
      （所以 `1+1`、`sum(rows...)`、`[x*2 for x in xs]` 都能直接得到值）
    - 注入变量由 extra 提供（Agent 会把最近一次查询结果塞成 `rows` / `cols`）
    - 超时由主线程 join 控制：超时后本次运行被丢弃，不算成功
    """
    timeout = timeout or TIMEOUT_SECONDS
    out: dict[str, Any] = {"ok": False, "result": None, "result_text": "", "stdout": "", "error": ""}
    try:
        tree = check_code(code)
    except SandboxError as exc:
        out["error"] = str(exc)
        return out

    body = tree.body
    last_expr = None
    if body and isinstance(body[-1], ast.Expr):      # 最后一行是裸表达式 → 单独 eval 兜取值
        last_expr = body[-1].value
        body = body[:-1]
    else:
        body = list(body)

    ns = _safe_namespace(extra)
    buf = io.StringIO()
    box: dict[str, Any] = {}

    def _task() -> None:
        stdout_backup = None
        try:
            import contextlib
            with contextlib.redirect_stdout(buf):
                if body:
                    exec(compile(ast.Module(body=body, type_ignores=[]), "<sandbox>", "exec"), ns)
                if last_expr is not None:
                    box["result"] = eval(compile(ast.Expression(last_expr), "<sandbox>", "eval"), ns)
                else:
                    box["result"] = ns.get("result")
        except BaseException as exc:                 # noqa: BLE001 —— 任何运行错都要收敛成文本
            box["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_task, daemon=True)
    try:
        worker.start()
    except Exception as exc:
        out["error"] = f"无法启动计算：{exc}"
        return out
    worker.join(timeout)

    if worker.is_alive():
        out["error"] = f"计算超时（>{timeout}s）：可能有死循环或数据量过大，请换更简单的写法"
        return out
    out["stdout"] = buf.getvalue().strip()[:MAX_OUTPUT_CHARS]
    if box.get("error"):
        out["error"] = str(box["error"])
        return out
    out["result"] = box.get("result")
    out["result_text"] = fmt(box.get("result"))
    out["ok"] = True
    return out


# --------------------------------------------------------------------------- #
# 自检：python services/pysandbox.py
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    failed = 0

    def check(name: str, got, want) -> None:
        nonlocal failed
        ok = got == want
        if not ok:
            failed += 1
        print(f"  [{'OK' if ok else 'NG'}] {name}" + ("" if ok else f"  期望={want!r} 实际={got!r}"))

    # ① 最后一行表达式取值
    r = run("1 + 2")
    check("表达式取值", r["result_text"], "3")

    # ② result 变量优先 / print 输出被捕获
    r = run("print('hi')\nresult = 42")
    check("捕获 stdout", r["stdout"], "hi")
    check("取 result 变量", r["result_text"], "42")

    # ③ 传入数据：rows 是最近一次查询的结果（list[dict]）
    rows = [{"amount": 100}, {"amount": 250}, {"amount": 80}]
    r = run("sum(x['amount'] for x in rows) / len(rows)", {"rows": rows})
    check("对数据求均值", r["result_text"], "143.3333")

    # ④ 常用库可用
    check("math 可用", run("math.sqrt(144)")["result_text"], "12")
    check("statistics 可用", run("statistics.median([1, 3, 2])")["result_text"], "2")
    if np is not None:
        check("numpy 可用", run("np.mean([1, 2, 3, 4])")["result_text"], "2.5")

    # ⑤ 静态拦截（在 exec 之前就被拦住）
    for name, code in (
        ("拦截 import", "import os\nos.listdir('.')"),
        ("拦截 open", "open('x.txt').read()"),
        ("拦截 eval", "eval('1+1')"),
        ("拦截下划线属性", "(1).__class__"),
        ("拦截 getattr", "getattr(int, 'real')"),
    ):
        r = run(code)
        check(name, r["ok"], False)

    # ⑥ 运行时错误收敛成文本（不抛异常）
    r = run("1 / 0")
    check("运行错误不崩", r["ok"], False)
    check("错误信息含类型", "ZeroDivisionError" in r["error"], True)

    # ⑦ 死循环：while 在静态阶段就被拒；超大 for 由步数预算拦住（不是靠线程超时）
    import time
    r = run("while True: pass")
    check("while 被静态拒绝", r["ok"], False)
    check("while 提示改写法", "不允许 while" in r["error"], True)

    started = time.time()
    r = run("total = 0\nfor i in range(10**12):\n    total += i\nresult = total")
    check("超长循环被预算拦下", r["ok"], False)
    check("预算提示", "循环迭代超过" in r["error"], True)
    check("预算拦截止损够快", time.time() - started < 5.0, True)

    # 正常量级的循环必须不受影响
    started = time.time()
    r = run("result = sum(i for i in range(100000))")
    check("正常循环不受影响", r["result_text"], "4999950000")
    check("插桩开销可接受", time.time() - started < 3.0, True)

    # ⑧ 渲染：长列表截断、浮点收敛
    check("长列表截断", "共" in fmt(list(range(200))), True)
    check("浮点收敛", fmt(1.5), "1.5")

    # ⑨ 语法错误提示
    check("语法错误友好", "语法错误" in run("def (:")["error"], True)

    print("全部通过 [OK]" if not failed else f"失败 {failed} 项 [NG]")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
