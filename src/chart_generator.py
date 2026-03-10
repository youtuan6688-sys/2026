"""
图表生成模块
从 pandas DataFrame 生成 matplotlib/seaborn 图表，保存为 PNG
供飞书 bot 发送给用户
"""

import logging
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无头模式，不需要 GUI
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
import pandas as pd

logger = logging.getLogger(__name__)

# 中文字体设置
_CN_FONTS = [
    "STHeiti", "Songti SC", "Lantinghei SC", "Hei",
    "PingFang HK", "STFangsong", "SimHei",
    "WenQuanYi Micro Hei", "Noto Sans CJK SC",
]

_font_initialized = False

def _setup_chinese_font():
    """找到系统可用的中文字体并设置"""
    global _font_initialized
    if _font_initialized:
        return
    _font_initialized = True

    # 强制重建 font cache 确保系统字体可用
    fm._load_fontmanager(try_read_cache=False)
    available = {f.name for f in fm.fontManager.ttflist}
    for font in _CN_FONTS:
        if font in available:
            plt.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["axes.unicode_minus"] = False
            logger.info(f"中文字体: {font}")
            return
    logger.warning("未找到中文字体，图表中文可能乱码")

# 统一样式
sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams.update({
    "figure.figsize": (10, 6),
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.3,
})

CHART_DIR = Path(tempfile.gettempdir()) / "xdm_charts"
CHART_DIR.mkdir(exist_ok=True)


def _save_chart(fig: plt.Figure, name: str) -> Path:
    """保存图表到临时目录，返回路径"""
    _setup_chinese_font()
    path = CHART_DIR / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    logger.info(f"图表已保存: {path} ({path.stat().st_size / 1024:.0f}KB)")
    return path


def bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str = "",
    top_n: int = 15,
    horizontal: bool = False,
) -> Path:
    """柱状图 — 适合分类对比"""
    plot_df = df.nlargest(top_n, y) if len(df) > top_n else df.copy()

    fig, ax = plt.subplots()
    if horizontal:
        plot_df_sorted = plot_df.sort_values(y)
        ax.barh(plot_df_sorted[x].astype(str), plot_df_sorted[y])
        ax.set_xlabel(y)
    else:
        ax.bar(plot_df[x].astype(str), plot_df[y])
        ax.set_ylabel(y)
        plt.xticks(rotation=45, ha="right")

    ax.set_title(title or f"{y} by {x}")
    return _save_chart(fig, f"bar_{x}_{y}")


def line_chart(
    df: pd.DataFrame,
    x: str,
    y: str | list[str],
    title: str = "",
) -> Path:
    """折线图 — 适合时间趋势"""
    fig, ax = plt.subplots()

    y_cols = [y] if isinstance(y, str) else y
    for col in y_cols:
        ax.plot(df[x], df[col], marker="o", markersize=3, label=col)

    if len(y_cols) > 1:
        ax.legend()

    ax.set_title(title or f"趋势: {', '.join(y_cols)}")
    plt.xticks(rotation=45, ha="right")

    # 如果 x 轴标签太多，只显示部分
    if len(df) > 20:
        step = max(1, len(df) // 10)
        ax.set_xticks(ax.get_xticks()[::step])

    return _save_chart(fig, f"line_{x}_{'_'.join(y_cols)}")


def pie_chart(
    df: pd.DataFrame,
    labels: str,
    values: str,
    title: str = "",
    top_n: int = 8,
) -> Path:
    """饼图 — 适合占比分析"""
    plot_df = df.nlargest(top_n, values).copy()

    # 超出部分合并为"其他"
    if len(df) > top_n:
        others_sum = df.nsmallest(len(df) - top_n, values)[values].sum()
        others_row = pd.DataFrame({labels: ["其他"], values: [others_sum]})
        plot_df = pd.concat([plot_df, others_row], ignore_index=True)

    fig, ax = plt.subplots()
    ax.pie(
        plot_df[values],
        labels=plot_df[labels],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.set_title(title or f"{values} 占比分布")
    return _save_chart(fig, f"pie_{labels}_{values}")


def summary_table(
    df: pd.DataFrame,
    title: str = "数据概况",
    max_rows: int = 20,
) -> Path:
    """将 DataFrame 渲染为表格图片"""
    show_df = df.head(max_rows)

    fig, ax = plt.subplots(figsize=(max(10, len(show_df.columns) * 2), max(4, len(show_df) * 0.4 + 1.5)))
    ax.axis("off")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

    table = ax.table(
        cellText=show_df.values,
        colLabels=show_df.columns,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.auto_set_column_width(list(range(len(show_df.columns))))

    # 表头样式
    for j in range(len(show_df.columns)):
        table[0, j].set_facecolor("#4472C4")
        table[0, j].set_text_props(color="white", fontweight="bold")

    return _save_chart(fig, f"table_{title[:20]}")


def auto_chart(df: pd.DataFrame, title: str = "") -> list[Path]:
    """自动分析 DataFrame 并生成合适的图表

    返回生成的图表路径列表（可能多张）
    """
    charts = []
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    datetime_cols = df.select_dtypes(include="datetime").columns.tolist()

    if not numeric_cols:
        logger.info("无数值列，仅生成表格")
        charts.append(summary_table(df, title=title or "数据预览"))
        return charts

    # 尝试识别日期列（字符串格式的日期）
    date_col = None
    for col in datetime_cols:
        date_col = col
        break
    if not date_col:
        for col in categorical_cols:
            sample = df[col].dropna().head(5)
            try:
                pd.to_datetime(sample)
                df[col] = pd.to_datetime(df[col], errors="coerce")
                date_col = col
                datetime_cols.append(col)
                categorical_cols.remove(col)
                break
            except (ValueError, TypeError):
                continue

    # 1. 有时间列 → 折线图
    if date_col and numeric_cols:
        y_cols = numeric_cols[:3]  # 最多3条线
        try:
            charts.append(line_chart(
                df.sort_values(date_col), x=date_col,
                y=y_cols, title=title or f"趋势分析",
            ))
        except Exception as e:
            logger.warning(f"折线图生成失败: {e}")

    # 2. 有分类列 + 数值列 → 柱状图
    if categorical_cols and numeric_cols:
        cat_col = categorical_cols[0]
        num_col = numeric_cols[0]
        unique_count = df[cat_col].nunique()
        if 2 <= unique_count <= 30:
            try:
                agg_df = df.groupby(cat_col, as_index=False)[num_col].sum()
                charts.append(bar_chart(
                    agg_df, x=cat_col, y=num_col,
                    title=title or f"{num_col} by {cat_col}",
                    horizontal=unique_count > 8,
                ))
            except Exception as e:
                logger.warning(f"柱状图生成失败: {e}")

        # 3. 分类占比 → 饼图（仅当类别 <= 10）
        if unique_count <= 10:
            try:
                agg_df = df.groupby(cat_col, as_index=False)[num_col].sum()
                charts.append(pie_chart(
                    agg_df, labels=cat_col, values=num_col,
                    title=title or f"{num_col} 占比",
                ))
            except Exception as e:
                logger.warning(f"饼图生成失败: {e}")

    # 兜底：如果一张图都没生成，给个表格
    if not charts:
        charts.append(summary_table(df, title=title or "数据预览"))

    return charts
