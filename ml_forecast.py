"""基于 sklearn 的月度业务指标预测模块。

数据源：本机 MySQL 三个业务库（金融 / 医疗 / 通信），全部按月聚合后建模预测。
模型：在 sklearn 线性回归 / Ridge / 随机森林 / 梯度提升 / SVR 中，用时间序列
    前向验证（最后一个自然分段）自动选出验证期 RMSE 最小的模型，再全量重训并
    递归滚动预测未来 N 个月，输出精度指标 + Markdown 预测报告。

用法
----
1. 命令行独立运行（生成 .md 报告文件）：
       python ml_forecast.py --db healthcare --horizon 6
       python ml_forecast.py --metric healthcare_revenue --horizon 6
       python ml_forecast.py --list
2. 被 Agent 调用：forecast_metric(metric, horizon) 返回摘要文本 + 报告路径。
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # 无 dotenv 时直接用系统环境变量
    pass

REPORT_DIR = PROJECT_ROOT / "reports"


# --------------------------------------------------------------------------- #
# 指标预设目录：三个库各提供一组“适合按月预测”的业务指标
# --------------------------------------------------------------------------- #
METRIC_CATALOG: dict[str, dict] = {
    # ---- 金融库 financial_asset_management ----
    "finance_trade_amount": {
        "db": "financial_asset_management", "table": "transactions",
        "date_col": "trade_date", "value_col": "transaction_amount", "agg": "sum",
        "name": "月度交易总金额", "unit": "元", "desc": "每日交易金额按自然月汇总",
    },
    "finance_new_clients": {
        "db": "financial_asset_management", "table": "clients",
        "date_col": "register_date", "value_col": None, "agg": "count",
        "name": "月度新开户数", "unit": "户", "desc": "客户注册时间按自然月计数",
    },
    "finance_avg_volatility": {
        "db": "financial_asset_management", "table": "risk_metrics",
        "date_col": "calc_date", "value_col": "volatility", "agg": "avg",
        "name": "月度平均组合波动率", "unit": "", "desc": "风险指标 volatility 按月求平均",
    },
    # ---- 医疗库 healthcare_analytics_competition ----
    "healthcare_revenue": {
        "db": "healthcare_analytics_competition", "table": "billing_transactions",
        "date_col": "transaction_date", "value_col": "net_amount", "agg": "sum",
        "name": "月度医疗净收入", "unit": "元", "desc": "bill 净额按交易日期汇总",
    },
    "healthcare_encounters": {
        "db": "healthcare_analytics_competition", "table": "medical_encounters",
        "date_col": "encounter_date", "value_col": None, "agg": "count",
        "name": "月度就诊人次(记录数)", "unit": "次", "desc": "就诊记录按开始时间计数",
    },
    "healthcare_order_amount": {
        "db": "healthcare_analytics_competition", "table": "medical_orders",
        "date_col": "start_datetime", "value_col": "total_price", "agg": "sum",
        "name": "月度医嘱费用总额", "unit": "元", "desc": "医嘱项目金额按开始时间汇总",
    },
    "healthcare_equipment_cost": {
        "db": "healthcare_analytics_competition", "table": "medical_equipment_usage",
        "date_col": "start_time", "value_col": "total_cost", "agg": "sum",
        "name": "月度设备使用成本", "unit": "元", "desc": "设备使用总费用按开始时间汇总",
    },
    # ---- 通信库 telecom_operations_db ----
    "telecom_bill_amount": {
        "db": "telecom_operations_db", "table": "monthly_bills",
        "date_col": "billing_month", "value_col": "total_amount", "agg": "sum",
        "name": "月度账单总额", "unit": "元", "desc": "账单金额按账期月份汇总",
    },
    "telecom_new_subscriptions": {
        "db": "telecom_operations_db", "table": "subscriptions",
        "date_col": "start_date", "value_col": None, "agg": "count",
        "name": "月度新订购数", "unit": "笔", "desc": "订购记录按生效日期计数",
    },
    "telecom_cdr_fee": {
        "db": "telecom_operations_db", "table": "cdr_detail",
        "date_col": "call_start_time", "value_col": "total_fee", "agg": "sum",
        "name": "月度通话费用总额", "unit": "元", "desc": "详单总费用按呼叫开始时间汇总",
    },
    "telecom_cdr_duration": {
        "db": "telecom_operations_db", "table": "cdr_detail",
        "date_col": "call_start_time", "value_col": "duration_seconds", "agg": "sum",
        "name": "月度通话总时长", "unit": "秒", "desc": "详单通话秒数按呼叫开始时间汇总",
    },
}

DB_ALIASES = {
    "financial_asset_management": "financial_asset_management",
    "finance": "financial_asset_management",
    "金融": "financial_asset_management",
    "金融库": "financial_asset_management",
    "healthcare_analytics_competition": "healthcare_analytics_competition",
    "healthcare": "healthcare_analytics_competition",
    "medical": "healthcare_analytics_competition",
    "医院": "healthcare_analytics_competition",
    "医疗": "healthcare_analytics_competition",
    "医疗库": "healthcare_analytics_competition",
    "telecom_operations_db": "telecom_operations_db",
    "telecom": "telecom_operations_db",
    "通信": "telecom_operations_db",
    "通信库": "telecom_operations_db",
}

_DB_LABEL = {
    "financial_asset_management": "金融库",
    "healthcare_analytics_competition": "医疗库",
    "telecom_operations_db": "通信库",
}

_MIN_MONTHS = 12  # 历史不足 12 个月不做预测
_MAX_HORIZON = 24  # 单次最多预测月数


def db_config() -> dict:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", "123456"),
        "charset": "utf8mb4",
        "connect_timeout": 8,
        "read_timeout": 60,
    }


def list_metrics_text() -> str:
    """返回全部可预测指标目录的纯文本表格，供 Agent / CLI --list 使用。"""
    lines = ["指标ID | 所属库 | 指标 | 聚合口径 | 说明"]
    lines.append("--- | --- | --- | --- | ---")
    for key, m in METRIC_CATALOG.items():
        agg = "COUNT(*)" if m["agg"] == "count" else f"{m['agg'].upper()}({m['value_col']})"
        lines.append(f"{key} | {_DB_LABEL[m['db']]} | {m['name']} | {agg} | {m['desc']}")
    return "\n".join(lines)


def _resolve_metric(metric: str | None, db: str | None) -> str:
    """确定要用的指标 key：优先显式 metric；其次按 db 给出该库默认指标。"""
    if metric:
        metric = metric.strip().lower()
        if metric in METRIC_CATALOG:
            return metric
        # 兼容：直接传“库名”想跑该库默认指标
        key = _db_default_metric(metric)
        if key:
            return key
        raise ValueError(f"未知指标 {metric!r}，可用指标见 --list / list_metrics_text()")
    db_key = _resolve_db(db)
    key = _db_default_metric(db_key)
    if not key:
        raise ValueError("缺少指标参数，请用 --metric 或 --db 指定一个业务库")
    return key


def _resolve_db(db: str | None) -> str:
    if not db:
        return ""
    key = DB_ALIASES.get(str(db).strip().lower())
    if not key:
        # 支持把完整库名/中文名直接映射
        key = DB_ALIASES.get(str(db).strip())
    if not key:
        raise ValueError(f"未知数据库 {db!r}，可用：finance/healthcare/telecom")
    return key


def _db_default_metric(metric_or_db: str) -> str | None:
    # 指标 key 直接命中
    if metric_or_db in METRIC_CATALOG:
        return metric_or_db
    db = _resolve_db(metric_or_db)
    if db == "financial_asset_management":
        return "finance_trade_amount"
    if db == "healthcare_analytics_competition":
        return "healthcare_revenue"
    if db == "telecom_operations_db":
        return "telecom_bill_amount"
    return None


# --------------------------------------------------------------------------- #
# 数据读取：按自然月聚合
# --------------------------------------------------------------------------- #
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DT_TYPES = {"datetime", "timestamp", "date"}


def _fetch_series(metric_key: str):
    """读取某指标的月度序列（列表 [(YYYY-MM, value)]，升序）。

    日期列若是 datetime/date 用 DATE_FORMAT；若是字符串则统一截取前 7 位
    （要求数据为 ISO 格式 YYYY-MM-DD…），两种都先探测前几行校验格式。
    """
    m = METRIC_CATALOG[metric_key]
    db, table = m["db"], m["table"]
    if not _IDENT_RE.match(table):
        raise ValueError(f"非法表名：{table}")
    for col in (m["date_col"], m["value_col"]):
        if col and not _IDENT_RE.match(col):
            raise ValueError(f"非法字段名：{col}")

    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("缺少 pymysql，请先执行：pip install pymysql") from exc

    conf = {**db_config(), "database": db}
    conn = pymysql.connect(**conf)
    try:
        with conn.cursor() as cur:
            # 判断日期列类型，决定按月表达式
            cur.execute(
                "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                (db, table, m["date_col"]),
            )
            row = cur.fetchone()
            dtype = (row[0] if row else "").lower()
            if dtype in _DT_TYPES:
                ym_expr = f"DATE_FORMAT(`{m['date_col']}`, '%Y-%m')"
            else:
                # varchar 存储的 ISO 日期：探测格式
                cur.execute(
                    f"SELECT `{m['date_col']}` FROM `{table}` WHERE `{m['date_col']}` IS NOT NULL LIMIT 5"
                )
                samples = [str(r[0]) for r in cur.fetchall()]
                if not samples or not re.match(r"^\d{4}-\d{2}", samples[0]):
                    raise RuntimeError(
                        f"字段 {m['date_col']} 不是可识别的 ISO 日期格式，无法按月聚合（样例：{samples[:2]}）"
                    )
                ym_expr = f"LEFT(`{m['date_col']}`, 7)"

            agg = m["agg"]
            if agg == "count":
                val_expr, label = "COUNT(*)", "笔数"
            else:
                val_expr = f"{agg.upper()}(`{m['value_col']}`)"
                label = f"{agg}({m['value_col']})"

            sql = (
                f"SELECT {ym_expr} AS ym, {val_expr} AS v "
                f"FROM `{table}` WHERE `{m['date_col']}` IS NOT NULL "
                f"GROUP BY ym ORDER BY ym"
            )
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    series = [(str(ym), float(v)) for ym, v in rows]
    if not series:
        raise RuntimeError(f"指标 {metric_key} 在 {db}.{table} 中没有数据")
    return series, db, table, label


# --------------------------------------------------------------------------- #
# sklearn 建模：前向验证选模型 + 递归滚动预测
# --------------------------------------------------------------------------- #
def _make_features(i: int, values: list[float], yms: list[tuple[int, int]], k: int) -> list[float]:
    """第 i 个月的特征：时间趋势 + 月度季节性(sin/cos) + 前 k 期滞后值。"""
    lags = [values[i - 1 - d] if i - 1 - d >= 0 else 0.0 for d in range(k)]
    year, month = yms[i]
    return [float(i), math.sin(2 * math.pi * (month - 1) / 12), math.cos(2 * math.pi * (month - 1) / 12), *lags]


def _next_ym(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _models():
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVR

    return [
        ("LinearRegression", make_pipeline(StandardScaler(), LinearRegression())),
        ("Ridge", make_pipeline(StandardScaler(), Ridge(alpha=1.0))),
        ("RandomForest", make_pipeline(StandardScaler(), RandomForestRegressor(
            n_estimators=300, min_samples_leaf=2, random_state=42))),
        ("GradientBoosting", make_pipeline(StandardScaler(), GradientBoostingRegressor(
            n_estimators=250, learning_rate=0.08, max_depth=3, random_state=42))),
        ("SVR", make_pipeline(StandardScaler(), SVR(kernel="rbf", C=1.0, epsilon=0.05))),
    ]


def forecast_series(values: list[float], months: list[tuple[int, int]], horizon: int = 6) -> dict:
    """对月度序列做 sklearn 回归预测。

    参数：values 与 months 等长且已按时间升序。
    返回：预测值、最佳模型、验证期指标、历史/预测月份、各模型对比等。
    """
    n = len(values)
    if n < _MIN_MONTHS:
        raise RuntimeError(f"历史数据仅 {n} 个月，不足 {_MIN_MONTHS} 个月，无法稳定预测")

    horizon = max(1, min(int(horizon), _MAX_HORIZON))
    k = min(12, max(3, n // 6))          # 滞后阶数
    test_len = min(12, max(4, n // 6))    # 验证集 = 最近 n//6 个月
    while n - test_len - k < 10:          # 保证训练样本充足
        test_len -= 1
        if test_len <= 2:
            break
    train_end = n - test_len

    # 生成“历史 + 未来”完整月份索引，便于递归预测
    yms = list(months)
    y, mth = yms[-1]
    for _ in range(horizon):
        y, mth = _next_ym(y, mth)
        yms.append((y, mth))

    def build_samples(values_src, start, end):
        xs, ys = [], []
        for i in range(start, end):
            xs.append(_make_features(i, values_src, yms, k))
            ys.append(values_src[i])
        return xs, ys

    X_tr, y_tr = build_samples(values, k, train_end)

    # ---- 前向验证：各模型都在训练段拟合，再在验证段递归预测 ----
    from sklearn.metrics import mean_absolute_error, mean_squared_error

    def _mape(y_true, y_pred):
        eps = 1e-9
        return 100.0 * sum(
            abs(t - p) / max(abs(t), eps) for t, p in zip(y_true, y_pred)
        ) / max(len(y_true), 1)

    best_name, best_pipe, best_rmse, best_stats = None, None, float("inf"), None
    model_compare = []
    for name, pipe in _models():
        pipe.fit(X_tr, y_tr)
        # 递归滚动预测验证段
        vals = list(values[:train_end])
        preds = []
        for i in range(train_end, n):
            feats = [_make_features(i, vals, yms, k)]
            pred = float(pipe.predict(feats)[0])
            preds.append(pred)
            vals.append(pred)
        rmse = math.sqrt(mean_squared_error(values[train_end:n], preds))
        mae = mean_absolute_error(values[train_end:n], preds)
        mape = _mape(values[train_end:n], preds)
        model_compare.append({"model": name, "rmse": rmse, "mae": mae, "mape": mape})
        if rmse < best_rmse:
            best_rmse, best_name, best_pipe, best_stats = rmse, name, pipe, (mae, mape)

    # ---- 全量重训 + 递归预测未来 ----
    X_all, y_all = build_samples(values, k, n)
    best_pipe.fit(X_all, y_all)
    vals = list(values)
    pred_future = []
    for i in range(n, n + horizon):
        feats = [_make_features(i, vals, yms, k)]
        p = float(best_pipe.predict(feats)[0])
        pred_future.append(p)
        vals.append(p)

    return {
        "horizon": horizon,
        "k": k,
        "train_size": train_end,
        "test_size": test_len,
        "best_model": best_name,
        "best_mae": best_stats[0],
        "best_rmse": best_rmse,
        "best_mape": best_stats[1],
        "model_compare": model_compare,
        "months": months,
        "values": values,
        "pred_future": pred_future,
        "month_labels": [f"{y:04d}-{m:02d}" for y, m in yms],
    }


# --------------------------------------------------------------------------- #
# Markdown 报告生成
# --------------------------------------------------------------------------- #
def _fmt(v: float | None) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "-"
    return f"{v:,.2f}"


def build_report(metric_key: str, result: dict, history_rows: list, chart_fname: str = "") -> str:
    """把预测结果拼成一份 Markdown 预测报告（chart_fname 非空时在开头嵌入趋势图）。"""
    m = METRIC_CATALOG[metric_key]
    n = len(result["values"])
    first, last = result["months"][0], result["months"][-1]
    horizon = result["horizon"]
    gap = None

    report = []
    report.append(f"# {m['name']}预测报告")
    report.append("")
    report.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    report.append(f"- 数据源：`{m['db']}.{m['table']}`（{_DB_LABEL[m['db']]}）")
    if m["agg"] == "count":
        report.append(f"- 指标口径：按 `{m['date_col']}` 对自然月计数（笔/人次）")
    else:
        report.append(f"- 指标口径：按 `{m['date_col']}` 对 `{m['value_col']}` 做 {m['agg']}，单位：{m['unit']}")
    report.append(f"- 历史时间范围：{first[0]:04d}-{first[1]:02d} ~ {last[0]:04d}-{last[1]:02d}，共 {n} 个月")
    report.append("")

    # 趋势图（Matplotlib PNG，报告文件同级相对路径，直接查看 md 即可见）
    if chart_fname:
        report.append(f"![{m['name']} 历史与预测趋势图]({chart_fname})")
        report.append("")

    # 模型与精度
    report.append("## 一、模型与精度")
    report.append("")
    report.append(
        f"- 建模方法：sklearn 机器学习（特征=时间趋势+月度季节性+前 {result['k']} 期滞后），"
        f"在各候选模型中做前向验证（训练 {result['train_size']} 个月 → 验证最近 {result['test_size']} 个月），"
        f"按验证集 RMSE 最小选出，再全量重训并递归预测未来 {horizon} 个月。"
    )
    report.append(f"- 最终选用模型：**{result['best_model']}**")
    report.append(
        f"- 验证期精度：RMSE = {_fmt(result['best_rmse'])}，MAE = {_fmt(result['best_mae'])}，MAPE = {result['best_mape']:.2f}%"
    )
    report.append("")
    report.append("候选模型验证精度对比：")
    report.append("")
    report.append("| 模型 | RMSE | MAE | MAPE |")
    report.append("| --- | --- | --- | --- |")
    for c in result["model_compare"]:
        report.append(f"| {c['model']} | {_fmt(c['rmse'])} | {_fmt(c['mae'])} | {c['mape']:.2f}% |")
    report.append("")

    # 预测表
    report.append("## 二、未来预测")
    report.append("")
    report.append("| 月份 | 预测值 | 环比变化 |")
    report.append("| --- | --- | --- |")
    prev = result["values"][-1]
    for i, p in enumerate(result["pred_future"]):
        lab = result["month_labels"][n + i]
        diff = p - prev
        pct = (diff / prev * 100) if prev else 0.0
        report.append(f"| {lab} | {_fmt(p)} | {diff:+,.2f}（{pct:+.1f}%） |")
        prev = p
    total = sum(result["pred_future"])
    report.append(f"\n预测期内合计：**{_fmt(total)}** {m['unit']}")
    report.append("")

    # 历史尾部
    report.append("## 三、最近 12 个月真实值（供对照）")
    report.append("")
    report.append("| 月份 | 实际值 |")
    report.append("| --- | --- |")
    for y, mo in result["months"][-12:]:
        pass
    tail = zip(result["months"][-12:], result["values"][-12:])
    for (y, mo), v in tail:
        report.append(f"| {y:04d}-{mo:02d} | {_fmt(v)} |")
    report.append("")

    # 结论
    report.append("## 四、结论")
    report.append("")
    last_v = result["values"][-1]
    fut_avg = sum(result["pred_future"]) / len(result["pred_future"])
    trend = "上升" if fut_avg > last_v else ("下降" if fut_avg < last_v else "持平")
    report.append(
        f"未来 {horizon} 个月该指标平均预测值为 {_fmt(fut_avg)} {m['unit']}，"
        f"较最近一个月（{_fmt(last_v)}）整体呈{trend}趋势；"
        f"历史 {n} 个月均值为 {_fmt(sum(result['values']) / n)} {m['unit']}。"
    )
    report.append(
        "说明：预测结果基于历史统计规律外推，供经营分析参考，不构成决策依据；"
        "政策、季节性活动等外部变化不在模型考虑范围内。"
    )
    report.append("")
    return "\n".join(report)


# --------------------------------------------------------------------------- #
# 对外主流程
# --------------------------------------------------------------------------- #
def run_forecast(metric: str | None = None, db: str | None = None,
                 horizon: int = 6, save: bool = True) -> dict:
    """端到端：取数 → sklearn 建模 → 预测 → （可选）写 Markdown 报告。

    返回 dict：包含 metric / name / summary(纯文本摘要) / report_path 等，
    供 Agent 工具或 CLI 直接使用。
    """
    key = _resolve_metric(metric, db)
    m = METRIC_CATALOG[key]
    series, dbname, table, agg_label = _fetch_series(key)

    months = []
    values = []
    for ym, v in series:
        y, mo = int(ym[:4]), int(ym[5:7])
        months.append((y, mo))
        values.append(v)

    result = forecast_series(values, months, horizon)

    # 摘要文本（Agent 回复时直接用）
    lines = [
        f"指标：{m['name']}（{_DB_LABEL[dbname]} · {dbname}.{table}，{agg_label}按自然月）",
        f"历史 {len(values)} 个月（{months[0][0]:04d}-{months[0][1]:02d} ~ {months[-1][0]:04d}-{months[-1][1]:02d}），"
        f"选用 sklearn {result['best_model']}，验证期 MAPE={result['best_mape']:.2f}%。",
        "预测值：",
    ]
    n = len(values)
    prev = values[-1]
    for i, p in enumerate(result["pred_future"]):
        lab = result["month_labels"][n + i]
        diff = p - prev
        pct = (diff / prev * 100) if prev else 0.0
        lines.append(f"  {lab}：{_fmt(p)} {m['unit']}（环比 {pct:+.1f}%）")
        prev = p
    fut_avg = sum(result["pred_future"]) / len(result["pred_future"])
    trend = "上升" if fut_avg > values[-1] else ("下降" if fut_avg < values[-1] else "持平")
    lines.append(f"结论：未来 {result['horizon']} 个月整体呈{trend}趋势，平均每月约 {_fmt(fut_avg)} {m['unit']}。")

    out = {
        "metric": key,
        "metric_name": m["name"],
        "db": dbname,
        "table": table,
        "agg": agg_label,
        "history_rows": len(values),
        "summary": "\n".join(lines),
        "result": result,
    }
    if save:
        # 先出趋势图，再写报告（报告头部嵌入图片）
        chart_path = _render_chart(key, m, result)
        if chart_path:
            out["chart_path"] = str(chart_path)
        path = save_report(key, result, report=build_report(key, result, series, chart_path.name if chart_path else ""))
        out["report_path"] = str(path)
        if out.get("chart_path"):
            out["summary"] += f"\n（趋势图：{Path(out['chart_path']).name}）"
    return out


def _render_chart(metric_key: str, m: dict, result: dict) -> Path | None:
    """生成“历史 + 预测”趋势图 PNG（Matplotlib 懒加载；缺库/失败返回 None 不中断流程）。"""
    try:
        import viz
    except Exception:
        return None
    n = len(result["values"])
    hist_labels = [f"{y:04d}-{mo:02d}" for y, mo in result["months"]]
    fut_labels = result["month_labels"][n:]
    try:
        return viz.plot_forecast(
            m["name"], m.get("unit", ""), hist_labels, result["values"],
            fut_labels, result["pred_future"], result["best_model"],
            prefix=f"chart_{metric_key}",
        )
    except Exception:
        return None


def save_report(metric_key: str, result: dict, report: str | None = None) -> Path:
    """把 Markdown 报告写入 reports/ 目录，返回文件路径。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{metric_key}_forecast_{ts}.md"
    path = REPORT_DIR / fname
    if report is None:
        report = build_report(metric_key, result, [])
    path.write_text(report, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CLI 入口：独立运行生成预测报告
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="sklearn 月度指标预测（生成 Markdown 报告）")
    parser.add_argument("--metric", help="指标 key（见 --list），如 healthcare_revenue")
    parser.add_argument("--db", choices=sorted({*DB_ALIASES}),
                        help="业务库：finance/healthcare/telecom（中文别名也可）")
    parser.add_argument("--horizon", type=int, default=6, help="预测未来几个月，默认 6，最大 24")
    parser.add_argument("--list", action="store_true", help="列出全部可预测指标")
    parser.add_argument("--json", action="store_true", help="同时以 JSON 输出预测结果")
    parser.add_argument("--no-save", action="store_true", help="只打印不写报告文件")
    args = parser.parse_args()

    if args.list:
        print(list_metrics_text())
        return

    out = run_forecast(args.metric, args.db, args.horizon, save=not args.no_save)
    print(out["summary"])
    if out.get("report_path"):
        print(f"\nMarkdown 预测报告：{out['report_path']}")
    if out.get("chart_path"):
        print(f"趋势图：{out['chart_path']}")
    if args.json:
        r = out["result"]
        payload = {
            "metric": out["metric"], "metric_name": out["metric_name"],
            "db": out["db"], "table": out["table"],
            "best_model": r["best_model"], "mape": round(r["best_mape"], 2),
            "pred_future": [round(x, 2) for x in r["pred_future"]],
            "month_labels": r["month_labels"][len(r["values"]):],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
