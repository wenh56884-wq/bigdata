"""Matplotlib 可视化工具（懒加载：matplotlib 只在真正出图时才导入，缺库不影响其它功能）。

能力
----
- plot_forecast(...)     预测报告趋势图（历史 + 未来预测折线），存 reports/*.png
- plot_query(...)        把查询结果（一列分类 + 一或多列数值）画成折线/柱状图，存 reports/*.png

统一约定：PNG 输出（Agg 后端）、中文字体自动探测、支持负数显示。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_ROOT / "reports"

_CANDIDATE_FONTS = [
    "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC",
    "Source Han Sans SC", "WenQuanYi Zen Hei", "DejaVu Sans",
]
# 与主界面（豆包风格 / Arco 色板）保持一致的配色
_PALETTE = ["#165DFF", "#00B42A", "#FF7D00", "#F53F3F", "#722ED1", "#0FC6C2", "#F7BA1E"]
_FONT_STATE = {"tried": False}


def _ensure_matplotlib():
    """惰性初始化 matplotlib（Agg），并配置中文字体与负号显示。返回 pyplot。"""
    import matplotlib

    matplotlib.use("Agg")  # 无 GUI 环境下生成图片
    import matplotlib.pyplot as plt

    if not _FONT_STATE["tried"]:
        _FONT_STATE["tried"] = True
        from matplotlib import font_manager

        have = {f.name for f in font_manager.fontManager.ttflist}
        chosen = next((f for f in _CANDIDATE_FONTS if f in have), "DejaVu Sans")
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.autolayout"] = False
    return plt


def _save(fig, prefix: str) -> Path | None:
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # 含微秒，避免同一秒内连画两张图时文件名冲突相互覆盖
        path = REPORT_DIR / f"{prefix}_{ts}.png"
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt_close(fig)
        return path
    except Exception:
        try:
            plt_close(fig)
        except Exception:
            pass
        return None


def plt_close(fig):
    import matplotlib.pyplot as plt

    plt.close(fig)


def _style_axis(ax, x_labels: list[str], x_rot: float = 60):
    import matplotlib.pyplot as plt

    ax.grid(axis="y", color="#E5E6EB", alpha=0.7, lw=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if len(x_labels) > 10:
        ax.tick_params(axis="x", rotation=x_rot, labelsize=7)
    fig = ax.figure
    fig.tight_layout()


def plot_forecast(
    metric_name: str,
    unit: str,
    history_labels: list[str],
    history_values: list[float],
    future_labels: list[str],
    future_values: list[float],
    model: str,
    prefix: str = "forecast",
) -> Path | None:
    """预测报告趋势图：历史实际（实线）+ 未来预测（虚线），在分界处画参考线。"""
    try:
        plt = _ensure_matplotlib()
        hist_l = list(history_labels)[-60:]  # 只展示最近 60 个月，避免过密
        hist_v = list(history_values)[-60:]
        fig, ax = plt.subplots(figsize=(10, 4.6), dpi=130)
        split_x = len(hist_l) - 1
        ax.plot(
            hist_l, hist_v, color="#165DFF", lw=2.2, marker="o", ms=3,
            label=f"历史实际（{len(hist_l)} 个月）",
        )
        if future_labels and future_values:
            xs = list(hist_l) + list(future_labels)
            ax.plot(
                future_labels, future_values, color="#FF7D00", lw=2.2,
                ls="--", marker="s", ms=4, label=f"预测（{len(future_values)} 个月）",
            )
            ax.axvline(x=split_x, color="#86909C", ls=":", lw=1.1)
            ax.annotate(
                "预测起点", xy=(split_x, future_values[0]), xytext=(split_x - max(1, len(xs) * 0.08), max(hist_v + future_values) * 1.03),
                fontsize=8, color="#86909C",
            )
        ax.set_title(f"{metric_name}：历史走势与未来预测（单位：{unit}）", fontsize=13)
        ax.set_ylabel(unit or "数值")
        ax.legend(loc="best", fontsize=9)
        _style_axis(ax, list(hist_l) + list(future_labels))
        if model:
            ax.text(0.01, -0.22, f"模型：{model}", transform=ax.transAxes, fontsize=8, color="#86909C")
        return _save(fig, prefix)
    except Exception:
        return None


def plot_query(
    title: str,
    x_labels: list[str],
    series_list: list[dict],
    ylabel: str = "",
    kind: str = "auto",
    prefix: str = "plot",
) -> Path | None:
    """把查询结果画成图。series_list: [{"name": 系列名, "values": [数值…]}, …]

    kind: "auto"（单系列且点数少→柱状，否则折线）| "line" | "bar"
    """
    try:
        plt = _ensure_matplotlib()
        if not series_list or len(x_labels) == 0:
            return None
        if kind == "auto":
            kind = "bar" if len(series_list) == 1 and len(x_labels) <= 24 else "line"
        fig, ax = plt.subplots(figsize=(max(7.5, len(x_labels) * 0.3), 4.6), dpi=130)
        for i, s in enumerate(series_list):
            color = _PALETTE[i % len(_PALETTE)]
            vals = s.get("values") or []
            if kind == "bar" and len(series_list) == 1:
                ax.bar(x_labels, vals, color=color, width=0.62, label=s.get("name") or "")
            else:
                ax.plot(x_labels, vals, color=color, marker="o", ms=3.4, lw=2.1, label=s.get("name") or "")
        ax.set_title(title or "查询结果可视化", fontsize=13)
        if ylabel:
            ax.set_ylabel(ylabel)
        if len(series_list) > 1 or kind == "bar":
            ax.legend(loc="best", fontsize=9)
        _style_axis(ax, x_labels)
        return _save(fig, prefix)
    except Exception:
        return None
