# -*- coding: utf-8 -*-
"""数据洞察：统计分析 / 关联分析 / 自动建模（异常检测 + 聚类挖掘）。

补齐「中级 / 高级」数据分析能力——项目此前只有 `ml_forecast`（时序预测）一个建模工具，
而且巧妇难为无米之炊：只能预测目录里写死的 11 个指标。这里提供的是**面向任意表**的能力：

    中级  describe / profile   数值列的完整统计画像（分位、偏度、缺失、离散度）
          correlation          Pearson + Spearman 相关矩阵，自动挑出强相关组合并解读
    高级  anomalies            三种方法投票的异常检测（z-score / IQR / IsolationForest）
          clusters             自动定 K 的聚类挖掘（轮廓系数选优）+ 每簇画像与自动命名

**ts এই所有人都кетинг** 不引入 pandas / scipy：只用 numpy + sklearn（项目现有依赖），
样本采集走 SQL `LIMIT`，控制内存与耗时。

隐私：任何**样本行**输出到回答之前都过一遍 `sanitize.mask_rows`，与 execute_sql 保持同一口径。

自检：python -m services.analytics.ml_insight（用合成数据，不需要连数据库）
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:                                    # 包式运行：python -m services.ml_insight
    from services.ops import sanitize
    from services.analytics.ml_forecast import METRIC_CATALOG, db_config
except ModuleNotFoundError:             # 直接运行脚本：python -m services.analytics.ml_insight
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.ops import sanitize
    from services.analytics.ml_forecast import METRIC_CATALOG, db_config

try:
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    _HAS_SKLEARN = True
except Exception:                                  # sklearn 缺失时仍能做统计分析（관련）
    _HAS_SKLEARN = False


MAX_SAMPLE = 20000          # 单次分析最多取多少行（超出先 LIMIT 采样，避免把库拖慢）
MAX_OUTLIERS = 15           # 最多列出多少个异常样本
MAX_CLUSTERS = 6

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNSAFE = re.compile(r"(;|--|/\*|\*/|\bunion\b|\binsert\b|\bupdate\b|\bdelete\b|\bdrop\b)", re.I)


# --------------------------------------------------------------------------- #
# 数据读取（只读、受限、可失败）
# --------------------------------------------------------------------------- #
def fetch_rows(database: str, table: str, columns: list[str] | None = None,
               where: str = "", limit: int = MAX_SAMPLE) -> tuple[list[str], list[list[Any]]]:
    """从业务库读一张表的样本；返回 (列名列表, 行列表)。非法标识符 / 危险条件一律拒绝。"""
    import pymysql

    if not _IDENT_RE.match(str(database or "")) or "." in str(database):
        raise ValueError(f"非法库名：{database}")
    if not _IDENT_RE.match(str(table or "")):
        raise ValueError(f"非法表名：{table}")
    for col in columns or []:
        if not _IDENT_RE.match(str(col or "")):
            raise ValueError(f"非法列名：{col}")
    if where and _UNSAFE.search(where):
        raise ValueError("WHERE 条件不允许包含子查询/注释/增删改语句")

    cols = ", ".join(f"`{c}`" for c in columns) if columns else "*"
    sql = f"SELECT {cols} FROM `{database}`.`{table}`"
    if where:
        sql += f" WHERE {where}"
    if limit:
        sql += f" LIMIT {int(limit)}"

    conn = pymysql.connect(database=database, **db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            headers = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return headers, rows


def _numeric_matrix(rows: list[list[Any]], headers: list[str],
                    columns: list[str] | None = None) -> tuple[list[str], np.ndarray]:
    """挑出**真正有度量意义**的数值列，转成 float 矩阵（缺失留作 NaN，由 _fill 兜）；

    为什么要有这道过滤：`client_id` / `manager_id` / `status` 这类列数值化后能算，
    但「客户号均值 400.5」既没意义又会误导模型。这里按「名字像 ID/编码/状态位」、
    「取值几乎不重复」、「只有两种整数取值」三条判据排除，并把原因留在
    `_numeric_matrix.last_skipped` 里，让上层能向用户说明「哪些列没参与统计」。
    """
    picked = [c for c in (columns or headers) if c in headers]
    cols: list[str] = []
    series: list[list[float]] = []
    skipped: list[dict] = []
    for col in picked:
        idx = headers.index(col)
        raw = [(r[idx] if idx < len(r) else None) for r in rows]
        values = _to_float_list(raw)
        if _missing_ratio(values) > 0.6:
            skipped.append({"列": col, "原因": "缺失过多"})
            continue
        reason = _skip_reason(col, values)
        if reason:
            skipped.append({"列": col, "原因": reason})
            continue
        cols.append(col)
        series.append(values)
    _numeric_matrix.last_skipped = skipped
    if not cols:
        return [], np.empty((0, 0))
    matrix = np.array(series, dtype=float).T        # shape: (n_rows, n_cols)
    return cols, matrix


_numeric_matrix.last_skipped = []

# 名字层面：主键 / 外键 / 编码 / 状态位
_ID_NAME_RE = re.compile(r"(^|_)(id|ids|code|no|num|seq|status|flag|version|is_[a-z_]+)($|_)", re.I)


def _skip_reason(col: str, values: list[float]) -> str:
    """判断某列该不该参与数值分析；返回空串表示保留。

    顺序很关键：**带小数的列一定是度量**（金额、比率、评分），直接放行；
    只有「全是整数」的列才接着看是不是标号 / 开关位——否则像 total_assets
    这种「高基数但确实是业务量」的列会被误杀成流水号。
    """
    if _ID_NAME_RE.search(str(col)):
        return "ID / 编码 / 状态类列，不做数值统计"
    clean = [v for v in values if v == v]           # 去掉 NaN
    if not clean:
        return "无有效数值"
    if not all(float(v).is_integer() for v in clean):
        return ""                                   # 有小数 → 视为度量指标保留
    n_unique = len(set(clean))
    if len(clean) >= 30 and n_unique / len(clean) > 0.95:
        return "整数且取值几乎不重复（疑似流水号 / 主键）"
    if len(clean) >= 20 and n_unique <= 2:
        return "只有两种取值（二值标志位）"
    return ""


def _to_float_list(raw: list[Any]) -> list[float]:
    out: list[float] = []
    for v in raw:
        if isinstance(v, bool):
            out.append(float(v))
        elif isinstance(v, (int, float)):
            out.append(float(v))
        elif v is None:
            out.append(float("nan"))
        else:
            try:
                out.append(float(str(v).strip()))
            except Exception:
                out.append(float("nan"))
    return out


def _nanmean_safe(values: list[float]) -> float:
    arr = np.array(values, dtype=float)
    return float(np.nanmean(arr)) if np.isfinite(arr).any() else float("nan")


def _missing_ratio(values: list[float]) -> float:
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        return 1.0
    return float(np.isnan(arr).sum()) / arr.size


def _fill(arr: np.ndarray) -> np.ndarray:
    """缺失值用列均值补齐（sklearn 不接受 NaN）。"""
    out = np.array(arr, dtype=float, copy=True)
    for j in range(out.shape[1]):
        col = out[:, j]
        bad = ~np.isfinite(col)
        if bad.all():
            out[:, j] = 0.0
        elif bad.any():
            out[bad, j] = float(np.nanmean(col[np.isfinite(col)]))
    return out


# --------------------------------------------------------------------------- #
# 中级：统计画像 / 相关分析
# --------------------------------------------------------------------------- #
def numeric_profile(matrix: np.ndarray, col_names: list[str]) -> list[dict]:
    """每列的完整统计画像：分位数、离散度、偏度、缺失率。"""
    out: list[dict] = []
    for j, name in enumerate(col_names):
        col = np.array(matrix[:, j], dtype=float)
        clean = col[np.isfinite(col)]
        if clean.size == 0:
            continue
        q1, med, q3 = (float(x) for x in np.percentile(clean, [25, 50, 75]))
        mean, std = float(clean.mean()), float(clean.std(ddof=1)) if clean.size > 1 else 0.0
        out.append({
            "列": name,
            "非空": int(clean.size),
            "缺失率": round(_missing_ratio(col.tolist()), 4),
            "均值": round(mean, 4),
            "标准差": round(std, 4),
            "最小": round(float(clean.min()), 4),
            "P25": round(q1, 4),
            "中位数": round(med, 4),
            "P75": round(q3, 4),
            "最大": round(float(clean.max()), 4),
            "变异系数": round(std / mean, 4) if mean else None,
            "偏度": round(3 * (mean - med) / std, 3) if std else 0.0,
        })
    return out


def _rank(values: np.ndarray) -> np.ndarray:
    """Spearman 用的秩（并列取平均秩，不依赖 scipy）。"""
    order = values.argsort()
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    # 处理并列：用 pandas 的 'average' 策略
    uniq_vals = np.unique(values)
    for v in uniq_vals:
        idx = np.where(values == v)[0]
        if idx.size > 1:
            ranks[idx] = ranks[idx].mean()
    return ranks


def correlation_matrix(matrix: np.ndarray, col_names: list[str]) -> dict:
    """Pearson + Spearman 双相关矩阵；挑出最强的若干对并给出解读。"""
    data = _fill(matrix)
    if data.shape[1] < 2 or data.shape[0] < 3:
        return {"pearson": [], "spearman": [], "top": [], "names": col_names}

    with np.errstate(invalid="ignore", divide="ignore"):
        pear = np.corrcoef(data, rowvar=False)
        ranks = np.apply_along_axis(_rank, 0, data)
        spear = np.corrcoef(ranks, rowvar=False)
    pear, spear = np.nan_to_num(pear), np.nan_to_num(spear)

    pairs: list[dict] = []
    n = len(col_names)
    for i in range(n):
        for j in range(i + 1, n):
            r = float(pear[i, j])
            pairs.append({"a": col_names[i], "b": col_names[j], "pearson": round(r, 4),
                          "spearman": round(float(spear[i, j]), 4)})
    pairs.sort(key=lambda p: abs(p["pearson"]), reverse=True)
    return {
        "names": col_names,
        "pearson": [[round(float(x), 3) for x in row] for row in pear],
        "spearman": [[round(float(x), 3) for x in row] for row in spear],
        "top": pairs[:6],
    }


def interpret_corr(r: float) -> str:
    a = abs(r)
    strength = "极强" if a >= 0.9 else "强" if a >= 0.7 else "中等" if a >= 0.4 else "弱" if a >= 0.2 else "几乎无"
    return f"{'正' if r > 0 else '负'}相关（{strength}，r={r:.2f}）"


# --------------------------------------------------------------------------- #
# 高级：异常检测（三方法投票）
# --------------------------------------------------------------------------- #
def detect_outliers(values: list[float], labels: list[str] | None = None) -> dict:
    """三种口径一起判异常：z-score（>3σ）、IQR（1.5 倍箱线）、IsolationForest。

    三选二以上命中才列为异常——单方法容易把「重尾分布的正常大客户」误判成异常。
    """
    arr = np.array(values, dtype=float)
    ok = np.isfinite(arr)
    if ok.sum() < 8:
        return {"count": 0, "items": [], "threshold": {}, "method_votes": {}}

    clean = arr[ok]
    idxs = list(np.where(ok)[0])
    mean, std = float(clean.mean()), float(clean.std(ddof=1)) or 1e-9
    q1, q3 = (float(x) for x in np.percentile(clean, [25, 75]))
    iqr = q3 - q1 or 1e-9

    votes: dict[int, list[str]] = {}
    scores_map: dict[int, float] = {}

    for pos, v in zip(idxs, clean):
        hit = []
        z = abs((v - mean) / std)
        if z > 3:
            hit.append("z>3σ")
        if v < q1 - 1.5 * iqr or v > q3 + 1.5 * iqr:
            hit.append("超出箱线图")
        if hit:
            votes[pos] = hit
            scores_map[pos] = round(z, 2)
        labels = labels or []

    if _HAS_SKLEARN and len(clean) >= 20:
        try:
            model = IsolationForest(contamination="auto", random_state=42, n_estimators=100)
            pred = model.fit_predict(clean.reshape(-1, 1))
            for pos, p in zip(idxs, pred):
                if p == -1:
                    votes.setdefault(pos, []).append("孤立森林")
                    scores_map.setdefault(pos, round(abs((arr[pos] - mean) / std), 2))
        except Exception:
            pass

    strong = [pos for pos, why in votes.items() if len(why) >= 2]
    if not strong:                                   # 没人拿到 ≥2 票：退而取偏离度最高的几个
        strong = sorted(scores_map, key=lambda p: -scores_map[p])[:min(5, len(scores_map))]
    strong.sort(key=lambda p: -scores_map.get(p, 0))
    strong = strong[:MAX_OUTLIERS]

    items = []
    for pos in strong:
        v = float(arr[pos])
        items.append({
            "位置": int(pos),
            "标签": str(labels[pos]) if pos < len(labels) else "",
            "取值": round(v, 4),
            "偏离倍率σ": scores_map.get(pos, 0.0),
            "相对均值": round(v / mean, 3) if mean else None,
            "命中方法": votes.get(pos, []),
        })
    return {
        "count": len(items),
        "items": items,
        "threshold": {"均值": round(mean, 4), "标准差": round(std, 4),
                      "箱线上界": round(q3 + 1.5 * iqr, 4), "箱线下界": round(q1 - 1.5 * iqr, 4)},
        "method_votes": {k: len(v) for k, v in
                         {"z>3σ": [p for p, w in votes.items() if "z>3σ" in w],
                          "超出箱线图": [p for p, w in votes.items() if "超出箱线图" in w],
                          "孤立森林": [p for p, w in votes.items() if "孤立森林" in w]}.items()},
    }


# --------------------------------------------------------------------------- #
# 高级：聚类挖掘（自动定 K + 簇画像）
# --------------------------------------------------------------------------- #
def cluster_profile(matrix: np.ndarray, col_names: list[str], max_k: int = MAX_CLUSTERS) -> dict:
    """标准化 → KMeans 在 k=2..max_k 里用轮廓系数选最优 → 给每簇出画像与自动命名。"""
    if not _HAS_SKLEARN:
        return {"error": "缺少 scikit-learn，无法聚类"}
    data = _fill(matrix)
    if data.shape[0] < 10 or data.shape[1] < 1:
        return {"error": f"样本太少（{data.shape[0]} 行），至少需要 10 行"}
    scaled = StandardScaler().fit_transform(data)
    k_max = max(2, min(max_k, int(math.sqrt(data.shape[0]))))

    best = {"k": 0, "score": -1.0, "model": None, "labels": None}
    for k in range(2, k_max + 1):
        try:
            model = KMeans(n_clusters=k, n_init=8, random_state=42)
            labels = model.fit_predict(scaled)
            if len(set(labels)) < 2:
                continue
            score = float(silhouette_score(scaled, labels))
        except Exception:
            continue
        if score > best["score"]:
            best = {"k": k, "score": score, "model": model, "labels": labels}
    if best["model"] is None:
        return {"error": "聚类失败（样本可能过于相似）"}

    labels = np.asarray(best["labels"])
    overall = scaled.mean(axis=0)
    clusters: list[dict] = []
    for cid in range(best["k"]):
        mask = labels == cid
        center = scaled[mask].mean(axis=0)
        # 「显著偏离」= 标准化后偏离整体均值 ≥0.6σ，按偏离程度取前 3 个特征
        deviations = sorted(
            ((abs(center[j] - overall[j]), j) for j in range(len(col_names))), reverse=True)
        marks = []
        for dev, j in deviations[:3]:
            if dev < 0.6:
                break
            raw_mean = float(np.nanmean(np.array(matrix[:, j], dtype=float)[mask]))
            marks.append({"列": col_names[j], "方向": "偏高" if center[j] > overall[j] else "偏低",
                          "偏离σ": round(float(center[j] - overall[j]), 2), "簇内均值": round(raw_mean, 3)})
        name_parts = [f"{m['列']}{m['方向']}" for m in marks[:2]]
        clusters.append({
            "簇": cid + 1,
            "样本数": int(mask.sum()),
            "占比": round(float(mask.sum()) / len(labels), 4),
            "特征": marks,
            "画像": "、".join(name_parts) if name_parts else "接近整体平均水平",
        })
    clusters.sort(key=lambda c: -c["样本数"])
    return {"k": best["k"], "silhouette": round(best["score"], 4), "clusters": clusters,
            "columns": col_names, "rows": int(data.shape[0])}


# --------------------------------------------------------------------------- #
# 渲染：给模型 / 用户看的 Markdown
# --------------------------------------------------------------------------- #
def render_profile(profile: list[dict], title: str = "统计画像") -> str:
    if not profile:
        return "（没有可用的数值列）"
    lines = [f"### {title}", "", "| 指标 | 非空 | 缺失率 | 均值 | 中位 | P25 | P75 | 标准差 | 变异系数 | 偏度 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for p in profile:
        lines.append(
            f"| {p['列']} | {p['非空']} | {p['缺失率']:.1%} | {p['均值']} | {p['中位数']} | "
            f"{p['P25']} | {p['P75']} | {p['标准差']} | {p['变异系数'] if p['变异系数'] is not None else '-'} "
            f"| {p['偏度']} |")
    return "\n".join(lines)


def render_corr(corr: dict) -> str:
    top = corr.get("top") or []
    if not top:
        return "（列数不足或样本太少，无法计算相关）"
    lines = ["相关性强弱（按 |r| 排序）：", ""]
    for pair in top:
        lines.append(f"- **{pair['a']}** ↔ **{pair['b']}**：皮尔逊 {pair['pearson']}，"
                     f"斯皮尔曼 {pair['spearman']} → {interpret_corr(pair['pearson'])}")
    return "\n".join(lines)


def render_outliers(result: dict, col: str) -> str:
    if not result.get("count"):
        return f"「{col}」未检出明显异常点（三种口径都没形成一致结论）。"
    th = result["threshold"]
    lines = [f"「{col}」检出 **{result['count']} 个异常点**"
             f"（参考：均值 {th['均值']}，σ={th['标准差']}，箱线范围 {th['箱线下界']} ~ {th['箱线上界']}）：", ""]
    for item in result["items"]:
        tag = f"（{item['标签']}）" if item.get("标签") else ""
        lines.append(f"- 取值 **{item['取值']}**{tag}：偏离 {item['偏离倍率σ']}σ，"
                     f"是均值的 {item['相对均值']} 倍；命中 {'+'.join(item['命中方法'])}")
    return "\n".join(lines)


def render_clusters(result: dict) -> str:
    if result.get("error"):
        return f"（聚类未完成：{result['error']}）"
    lines = [f"自动聚类结果：在轮廓系数最优时分为 **{result['k']} 簇**"
             f"（silhouette={result['silhouette']}，基于 {result['rows']} 行样本）", ""]
    for c in result["clusters"]:
        lines.append(f"- **第{c['簇']}簇 · {c['画像']}**：{c['样本数']} 条，占 {c['占比']:.1%}")
        for m in c["特征"]:
            lines.append(f"    - {m['列']}：{m['方向']}（偏离整体 {m['偏离σ']}σ，簇内均值 {m['簇内均值']}）")
    return "\n".join(lines)


def mask_sample_rows(headers: list[str], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """样本行在进回答之前统一过一遍脱敏（与 execute_sql 同一口径）。"""
    masked_rows, cols, _ = None, None, None
    cols, masked_rows, _masked = sanitize.mask_rows(list(headers), [list(r) for r in rows])
    return cols, masked_rows


# --------------------------------------------------------------------------- #
# 自检：python -m services.analytics.ml_insight（合成数据，不需要数据库）
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    failed = 0

    def check(name: str, got, want) -> None:
        nonlocal failed
        ok = got == want
        if not ok:
            failed += 1
        print(f"  [{'OK' if ok else 'NG'}] {name}" + ("" if ok else f"  期望={want!r} 实际={got!r}"))
    rng = np.random.default_rng(7)

    # ① 统计画像：已知均值和量级
    base = rng.normal(100, 15, 500)
    prof = numeric_profile(np.column_stack([base]), ["金额"])
    check("画像有一列", len(prof), 1)
    check("均值接近 100", abs(prof[0]["均值"] - base.mean()) < 1e-3, True)
    check("缺失率为 0", prof[0]["缺失率"], 0.0)

    # ② 缺失值：按列均值补齐后不参与统计百分比
    with_nan = np.where(rng.random(500) < 0.2, np.nan, base)
    prof2 = numeric_profile(np.column_stack([with_nan]), ["金额"])
    check("缺失率被正确统计", abs(prof2[0]["缺失率"] - float(np.isnan(with_nan).mean())) < 0.01, True)

    # ③ 相关：构造强正相关，验证相关系数 > 0.9 且被识别为极强
    x = rng.normal(size=200)
    corr = correlation_matrix(np.column_stack([x, x * 2 + rng.normal(0, 0.1, 200)]), ["a", "b"])
    check("强相关被检出", abs(corr["top"][0]["pearson"]) > 0.9, True)
    check("解读含极强", "极强" in interpret_corr(corr["top"][0]["pearson"]), True)

    # ④ 异常检测：明显离群点必须被抓到
    vals = list(rng.normal(100, 5, 300)) + [500.0]
    labels = [f"行{i}" for i in range(301)]
    out = detect_outliers(vals, labels)
    check("检出异常", out["count"] > 0, True)
    check("最大异常是注入的那个", out["items"][0]["取值"], 500.0)
    check("异常带标签", out["items"][0]["标签"], "行300")

    # ⑤ 聚类：三簇高斯混合应自动分出 3 簇
    c1 = rng.normal([0, 0], 0.4, size=(80, 2))
    c2 = rng.normal([6, 6], 0.4, size=(80, 2))
    c3 = rng.normal([-6, 7], 0.4, size=(80, 2))
    data = np.vstack([c1, c2, c3])
    clu = cluster_profile(data, ["x", "y"])
    check("自动选出 3 簇", clu.get("k"), 3)
    check("轮廓系数高", clu["silhouette"] > 0.7, True)
    check("每簇都有画像", all(c["画像"] for c in clu["clusters"]), True)

    # ⑥ 渲染函数都不崩、且输出可读
    check("渲染画像", render_profile(prof).startswith("### 统计画像"), True)
    check("渲染相关", render_corr(corr).startswith("相关性强弱"), True)
    check("渲染异常", "异常点" in render_outliers(out, "金额"), True)
    check("渲染聚类", "自动聚类结果" in render_clusters(clu), True)

    # ⑦ 样本太少 / 无数值列时的兜底
    check("样本不足给 error", "error" in cluster_profile(np.zeros((5, 2)), ["a", "b"]), True)
    check("异常样本太少返回 0", detect_outliers([1.0, 2.0])["count"], 0)

    # ⑧ 列名清洗与注入防护
    for name, fn in (
        ("拒绝带点的库名", lambda: fetch_rows("a.b", "t")),
        ("拒绝非法表名", lambda: fetch_rows("db", "t;drop")),
        ("拒绝危险 WHERE", lambda: fetch_rows("db", "t", where="1=1; DROP TABLE x")),
    ):
        try:
            fn()
            ok = False
        except ValueError:
            ok = True
        except Exception:
            ok = False
        check(name, ok, True)

    # ⑨ 指标目录仍然可用（说明与 ml_forecast 的耦合没坏）
    check("指标目录可用", len(METRIC_CATALOG) > 0, True)

    print("全部通过 [OK]" if not failed else f"失败 {failed} 项 [NG]")
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _selftest() else 0)
