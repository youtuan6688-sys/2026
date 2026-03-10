"""Stock data query via akshare (free, no API key needed).

Supports: A-shares, HK stocks.
"""

import logging
import re

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# Common stock name → code mappings for quick lookup
_ALIASES = {
    "东山精密": "002384",
    "小米": "01810",
    "腾讯": "00700",
    "阿里": "09988",
    "比亚迪": "002594",
    "茅台": "600519",
    "宁德时代": "300750",
}


def _normalize_code(query: str) -> tuple[str, str]:
    """Parse user input into (code, market). Market: 'a' or 'hk'."""
    query = query.strip()

    # Check aliases first
    for name, code in _ALIASES.items():
        if name in query:
            market = "hk" if len(code) == 5 else "a"
            return code, market

    # Extract code from input (e.g., "002384", "01810.HK", "SH600519")
    # HK pattern: 5-digit or .HK suffix
    hk_match = re.search(r"(\d{5})(?:\.HK)?", query, re.IGNORECASE)
    if hk_match:
        return hk_match.group(1), "hk"

    # A-share pattern: 6-digit
    a_match = re.search(r"(\d{6})", query)
    if a_match:
        return a_match.group(1), "a"

    # Try as stock name — search in A-share list
    return query, "name"


def query_stock(query: str) -> str:
    """Query stock info and return formatted text."""
    code, market = _normalize_code(query)

    if market == "name":
        return _search_by_name(code)
    elif market == "hk":
        return _query_hk(code)
    else:
        return _query_a_share(code)


def _search_by_name(name: str) -> str:
    """Search stock by name in A-share market."""
    try:
        df = ak.stock_zh_a_spot_em()
        matches = df[df["名称"].str.contains(name, na=False)]
        if matches.empty:
            # Try HK
            df_hk = ak.stock_hk_spot_em()
            matches_hk = df_hk[df_hk["名称"].str.contains(name, na=False)]
            if matches_hk.empty:
                return f"没找到「{name}」相关的股票，试试输入代码？"
            return _format_spot_rows(matches_hk.head(5), market="hk")
        return _format_spot_rows(matches.head(5), market="a")
    except Exception as e:
        logger.error(f"Stock search error: {e}", exc_info=True)
        return f"查询出错: {e}"


def _query_a_share(code: str) -> str:
    """Query A-share stock real-time data."""
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            return f"没找到 A 股代码 {code}"

        r = row.iloc[0]
        name = r.get("名称", "")
        price = r.get("最新价", 0)
        change_pct = r.get("涨跌幅", 0)
        change_amt = r.get("涨跌额", 0)
        volume = r.get("成交量", 0)
        turnover = r.get("成交额", 0)
        high = r.get("最高", 0)
        low = r.get("最低", 0)
        open_price = r.get("今开", 0)
        prev_close = r.get("昨收", 0)
        amplitude = r.get("振幅", 0)
        turnover_rate = r.get("换手率", 0)
        pe = r.get("市盈率-动态", "")
        market_cap = r.get("总市值", 0)

        arrow = "🔴" if change_pct and change_pct < 0 else "🟢" if change_pct and change_pct > 0 else "⚪"

        cap_str = _format_cap(market_cap)
        vol_str = f"{volume / 10000:.0f}万手" if volume else "-"
        amt_str = _format_cap(turnover)

        return (
            f"{arrow} {name}({code})\n"
            f"最新价: {price}  涨跌: {change_amt:+.2f} ({change_pct:+.2f}%)\n"
            f"今开: {open_price}  昨收: {prev_close}\n"
            f"最高: {high}  最低: {low}  振幅: {amplitude}%\n"
            f"成交量: {vol_str}  成交额: {amt_str}\n"
            f"换手率: {turnover_rate}%  市盈率: {pe}\n"
            f"总市值: {cap_str}"
        )
    except Exception as e:
        logger.error(f"A-share query error for {code}: {e}", exc_info=True)
        return f"查询 {code} 出错: {e}"


def _query_hk(code: str) -> str:
    """Query HK stock real-time data."""
    try:
        df = ak.stock_hk_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            return f"没找到港股代码 {code}"

        r = row.iloc[0]
        name = r.get("名称", "")
        price = r.get("最新价", 0)
        change_pct = r.get("涨跌幅", 0)
        change_amt = r.get("涨跌额", 0)
        volume = r.get("成交量", 0)
        turnover = r.get("成交额", 0)
        high = r.get("最高", 0)
        low = r.get("最低", 0)

        arrow = "🔴" if change_pct and change_pct < 0 else "🟢" if change_pct and change_pct > 0 else "⚪"

        vol_str = f"{volume / 10000:.0f}万股" if volume else "-"
        amt_str = _format_cap(turnover)

        return (
            f"{arrow} {name}({code}.HK)\n"
            f"最新价: {price} HKD  涨跌: {change_amt:+.2f} ({change_pct:+.2f}%)\n"
            f"最高: {high}  最低: {low}\n"
            f"成交量: {vol_str}  成交额: {amt_str}"
        )
    except Exception as e:
        logger.error(f"HK stock query error for {code}: {e}", exc_info=True)
        return f"查询港股 {code} 出错: {e}"


def _format_spot_rows(df: pd.DataFrame, market: str = "a") -> str:
    """Format multiple stock rows for display."""
    lines = []
    for _, r in df.iterrows():
        code = r.get("代码", "")
        name = r.get("名称", "")
        price = r.get("最新价", 0)
        change_pct = r.get("涨跌幅", 0)
        arrow = "🔴" if change_pct and change_pct < 0 else "🟢" if change_pct and change_pct > 0 else "⚪"
        suffix = ".HK" if market == "hk" else ""
        lines.append(f"{arrow} {name}({code}{suffix}) {price} ({change_pct:+.2f}%)")
    return "\n".join(lines)


def _format_cap(value) -> str:
    """Format large numbers to 亿/万."""
    try:
        v = float(value)
        if v >= 1e8:
            return f"{v / 1e8:.2f}亿"
        if v >= 1e4:
            return f"{v / 1e4:.0f}万"
        return f"{v:.0f}"
    except (ValueError, TypeError):
        return str(value)
