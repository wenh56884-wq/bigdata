"""独立运行的 Sklearn 机器学习预测脚本（三个业务库通用）。

不依赖聊天服务，直接训练 sklearn 模型并输出 Markdown 预测报告。

常用示例
--------
    python predict.py                          # 三个库各跑其默认收入指标，生成 3 份报告
    python predict.py --db healthcare          # 只跑医疗库默认指标
    python predict.py --metric telecom_bill_amount --horizon 12   # 指定指标 + 预测 12 个月
    python predict.py --list                   # 查看全部可预测指标 key
    python predict.py --all-metrics --no-save  # 遍历全部指标、只打印结果不写文件
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

from services.ml_forecast import (
    METRIC_CATALOG,
    _db_default_metric,
    list_metrics_text,
    run_forecast,
)

# 每个库的默认（代表性）指标 key
_DB_DEFAULT = {
    "financial_asset_management": "finance_trade_amount",
    "healthcare_analytics_competition": "healthcare_revenue",
    "telecom_operations_db": "telecom_bill_amount",
}


def _resolve_targets(metric: str | None, db: str | None, all_metrics: bool) -> list[str]:
    """决定本次要预测哪些指标 key。优先级：--metric > --db > 默认三库指标。"""
    if metric:
        key = metric.strip().lower()
        if key not in METRIC_CATALOG:
            raise ValueError(f"未知指标 {key!r}，用 --list 查看可用指标")
        return [key]
    if all_metrics:
        return sorted(METRIC_CATALOG)
    if db:
        key = _db_default_metric(db)
        if not key:
            raise ValueError(f"未知数据库 {db!r}，可用：finance / healthcare / telecom")
        return [key]
    return sorted(_DB_DEFAULT.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sklearn 机器学习月度指标预测（金融/医疗/通信三库），生成 Markdown 预测报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python predict.py                          # 三库默认指标\n"
            "  python predict.py --db finance --horizon 12\n"
            "  python predict.py --metric healthcare_revenue\n"
        ),
    )
    parser.add_argument("--metric", help="指定指标 key（见 --list）")
    parser.add_argument("--db", help="指定业务库（跑其默认指标）：finance/healthcare/telecom 或中文：金融/医疗/通信")
    parser.add_argument("--horizon", type=int, default=6, help="预测未来几个月，默认 6，最大 24")
    parser.add_argument("--out", metavar="FILE", help="把报告的 .md 保存/复制到指定路径（可选）")
    parser.add_argument("--all-metrics", action="store_true", help="遍历目录中全部指标各出一份报告")
    parser.add_argument("--list", action="store_true", help="列出全部可预测指标")
    parser.add_argument("--no-save", action="store_true", help="只打印结果，不生成报告文件")
    args = parser.parse_args()

    if args.list:
        print(list_metrics_text())
        return

    try:
        keys = _resolve_targets(args.metric, args.db, args.all_metrics)
    except ValueError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return 2

    print(f"本次预测 {len(keys)} 个指标（horizon={args.horizon} 个月）\n" + "=" * 60)
    paths: list[str] = []
    for key in keys:
        name = METRIC_CATALOG[key]["name"]
        print(f"\n[预测] {name}（{key}）")
        try:
            out = run_forecast(metric=key, horizon=args.horizon, save=not args.no_save)
        except Exception as exc:
            print(f"  [失败] 预测异常：{exc}")
            continue
        print(out["summary"])
        if out.get("report_path"):
            paths.append(out["report_path"])
            if args.out and len(keys) == 1:
                target = os.path.abspath(args.out)
                shutil.copyfile(out["report_path"], target)
                print(f"  报告已另存为：{target}")
    if paths:
        print("\n" + "=" * 60)
        print("本次生成的 Markdown 预测报告：")
        for p in paths:
            print("  -", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
