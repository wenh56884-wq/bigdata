#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval_jiso.py 核心函数的离线单元测试（不依赖数据库 / 不调用模型）。"""
import sys
from decimal import Decimal
from datetime import date, datetime

sys.path.insert(0, ".")
from eval_jiso import extract_sql, result_counter, _cell_key  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    if not ok:
        failures.append(name)
    print(f"  {'[OK]' if ok else '[FAIL]'} {name}" + ("" if ok else f"\n        got={got!r}\n        want={want!r}"))


# ---------- extract_sql ----------
check("纯 SQL 原样返回",
      extract_sql("SELECT * FROM clients WHERE client_name LIKE '王%'"),
      "SELECT * FROM clients WHERE client_name LIKE '王%'")

check("剥 sql 围栏",
      extract_sql("```sql\nSELECT COUNT(*) FROM products\n```"),
      "SELECT COUNT(*) FROM products")

check("剥无语言围栏",
      extract_sql("```\nSELECT 1\n```"),
      "SELECT 1")

check("剥前缀解释 + 截掉分号后内容",
      extract_sql("这是 SQL：\nSELECT 1;\n说明：查询了 x"),
      "SELECT 1")

check("WITH 开头保留",
      extract_sql("WITH t AS (SELECT 1) SELECT * FROM t;"),
      "WITH t AS (SELECT 1) SELECT * FROM t")

check("SQL: 前缀",
      extract_sql("SQL: SELECT a, b FROM t"),
      "SELECT a, b FROM t")

check("无 SQL 关键字返回空串",
      extract_sql("抱歉，我无法回答这个问题"),
      "")

check("空输入", extract_sql(""), "")

check("SQL 内部字符串含分号不受影响",
      extract_sql("SELECT ';' AS x FROM t"),
      "SELECT ';' AS x FROM t")

check("多语句只取第一句",
      extract_sql("SELECT 1; SELECT 2"),
      "SELECT 1")

check("结尾分号去掉",
      extract_sql("SELECT 1;"),
      "SELECT 1")

# ---------- 数值 / 单元格归一化 ----------
check("Decimal 尾零归一", _cell_key(Decimal("991.00")), _cell_key(Decimal("991")))
check("int 与 Decimal 一致", _cell_key(123), _cell_key(Decimal("123.0")))
check("float 与 Decimal 一致", _cell_key(2.5), _cell_key(Decimal("2.50")))
check("None", _cell_key(None), ("null", ""))
check("bytes 解码", _cell_key(b"abc"), ("str", "abc"))
check("date", _cell_key(date(2024, 1, 2)), ("dt", "2024-01-02"))
check("datetime 无微秒不加尾巴", _cell_key(datetime(2024, 1, 2, 3, 4, 5)), ("dt", "2024-01-02 03:04:05"))

# ---------- 行序无关比对 ----------
r1 = [(123, "a", None), (Decimal("991.0"), "b", 5)]
r2 = [(Decimal("991.00"), "b", Decimal("5")), (123, "a", None)]
r3 = [(123, "a", None), (Decimal("991.0"), "c", 5)]
check("行序无关 + 数值形态无关判等", result_counter(r1) == result_counter(r2), True)
check("内容不同判不等", result_counter(r1) == result_counter(r3), False)

# ---------- 生成 SQL 的只读校验（复用 agent 逻辑） ----------
import agent as ag  # noqa: E402

try:
    ag._validate_readonly("SELECT * FROM clients;")
    check("正常 SELECT 通过校验", True, True)
except ValueError as exc:
    check("正常 SELECT 通过校验", f"被拒: {exc}", True)

for bad, label in [
    ("DROP TABLE clients", "DROP 被拒"),
    ("SELECT 1; SELECT 2", "多语句被拒"),
    ("UPDATE clients SET x=1", "UPDATE 被拒"),
]:
    try:
        ag._validate_readonly(bad)
        check(label, "未拦截", "被拒绝")
    except ValueError:
        check(label, True, True)

print()
if failures:
    print(f"共 {len(failures)} 个失败：{failures}")
    sys.exit(1)
print("全部测试通过 ✓")
