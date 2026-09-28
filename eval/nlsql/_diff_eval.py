#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比两份 jiso 评测明细（v1 vs v2），量化优化效果。

用法: python -m eval.nlsql._diff_eval <v1_details.jsonl> <v2_details.jsonl>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path


def load(path):
    recs = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        recs[(r["db"], str(r["id"]))] = r
    return recs


v1 = load(sys.argv[1])
v2 = load(sys.argv[2])
common = sorted(set(v1) & set(v2))
print(f"v1 题数 {len(v1)} / v2 题数 {len(v2)} / 共同题数 {len(common)}")

p1 = sum(1 for k in common if v1[k]["status"] == "pass")
p2 = sum(1 for k in common if v2[k]["status"] == "pass")
print(f"通过数: v1 = {p1} ({p1/len(common)*100:.1f}%)  →  v2 = {p2} ({p2/len(common)*100:.1f}%)")

fixed = [k for k in common if v1[k]["status"] != "pass" and v2[k]["status"] == "pass"]
regressed = [k for k in common if v1[k]["status"] == "pass" and v2[k]["status"] != "pass"]
still_bad = [k for k in common if v1[k]["status"] != "pass" and v2[k]["status"] != "pass"]
print(f"\n修复（错→对）: {len(fixed)} 题")
print(f"回退（对→错）: {len(regressed)} 题")
print(f"仍错: {len(still_bad)} 题")

print(f"\n按库统计修复/回退:")
for db in ["financial_asset_management", "healthcare_analytics_competition", "telecom_operations_db"]:
    f = sum(1 for k in fixed if k[0] == db)
    r = sum(1 for k in regressed if k[0] == db)
    s = sum(1 for k in still_bad if k[0] == db)
    print(f"  {db}: 修复 {f} / 回退 {r} / 仍错 {s}")

print(f"\n=== 回退案例全部列出（最多 15）===")
for k in regressed[:15]:
    r1, r2 = v1[k], v2[k]
    print(f"\n[{r2['title']}] #{r2['id']} {r2['problem'][:70]}")
    print(f"  v1: {r1['status']} | {r1['detail'][:60]}")
    print(f"  v2: {r2['status']} | {r2['detail'][:60]}")
    print(f"  v2 生成: {r2['gen_sql'].replace(chr(10),' ')[:150]}")
    print(f"  参考: {r2['ref_sql'].replace(chr(10),' ')[:150]}")

print(f"\n=== 修复案例抽样（10 个）===")
for k in fixed[:10]:
    r1, r2 = v1[k], v2[k]
    print(f"[{r2['title']}] #{r2['id']} {r2['problem'][:60]}")
    print(f"  v1 错因: {r1['detail'][:70]}")

print(f"\n=== 仍错案例状态分布 ===")
print(dict(Counter(v2[k]["status"] for k in still_bad)))
print(f"\n=== 仍错案例 v2 错因细分 ===")
kid = Counter()
for k in still_bad:
    d = v2[k]["detail"]
    m = re.search(r"列数不同：生成 (\d+) 列 vs 参考 (\d+) 列", d)
    if m:
        g, ref = int(m.group(1)), int(m.group(2))
        kid["列少" if g < ref else "列多"] += 1
    elif "行集不同" in d:
        m = re.search(r"生成 (\d+) 行 vs 参考 (\d+) 行", d)
        if m and m.group(1) == m.group(2):
            kid["同行数不同内容"] += 1
        else:
            kid["行数不同"] += 1
    else:
        kid[v2[k]["status"]] += 1
print(dict(kid))
