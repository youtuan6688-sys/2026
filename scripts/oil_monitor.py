"""
国际原油价格监控 (WTI + 布伦特)
每30分钟运行，有异动时推送飞书提醒，无异动静默。
数据源：金十数据 / 新浪财经期货接口
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from config.settings import Settings
from src.feishu_sender import FeishuSender

# ── 配置 ──────────────────────────────────────────────────────────────────────

STATE_FILE = PROJECT_DIR / "data" / "oil_monitor_state.json"
ADMIN_OPEN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"
GROUP_CHAT_ID = "oc_4f17f731a0a3bf9489c095c26be6dedc"

# 异动阈值
ALERT_CHANGE_30MIN = 1.0   # 30分钟涨跌 ≥ 1%
ALERT_DAILY_CHANGE = 3.0   # 日内累计涨跌 ≥ 3%

CN_TZ = timezone(timedelta(hours=8))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── 行情获取 ──────────────────────────────────────────────────────────────────

def fetch_oil_prices() -> dict | None:
    """从新浪财经期货接口获取 WTI 和布伦特原油价格。

    新浪期货代码:
      - WTI: hf_CL (NYMEX 原油连续)
      - Brent: hf_OIL (ICE 布伦特连续)
    """
    codes = {"WTI": "hf_CL", "Brent": "hf_OIL"}
    code_str = ",".join(codes.values())
    url = f"https://hq.sinajs.cn/list={code_str}"
    headers = {"Referer": "https://finance.sina.com.cn/"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        lines = resp.text.strip().split("\n")
    except Exception as e:
        logger.error(f"Failed to fetch oil prices: {e}")
        return None

    result = {}
    for name, code in codes.items():
        for line in lines:
            if code not in line:
                continue
            try:
                data_str = line.split('"')[1]
                if not data_str:
                    continue
                fields = data_str.split(",")
                # 新浪期货格式: 名称,买价,卖价,最高,最低,昨收,开盘,持仓量,...
                # 不同品种字段数不同，取关键字段
                price = float(fields[0]) if fields[0] else None
                prev_close = float(fields[7]) if len(fields) > 7 and fields[7] else None
                if price and price > 0:
                    result[name] = {
                        "price": price,
                        "prev_close": prev_close,
                    }
            except (IndexError, ValueError) as e:
                logger.warning(f"Parse error for {name}: {e}")

    # 备用方案：如果新浪接口无数据，尝试东方财富
    if not result:
        result = _fetch_from_eastmoney()

    return result if result else None


def _fetch_from_eastmoney() -> dict:
    """备用数据源：东方财富期货行情"""
    result = {}
    # 东方财富期货代码: WTI=NYMEX_CL, Brent=IPE_OIL
    codes = {
        "WTI": "https://push2.eastmoney.com/api/qt/stock/get?secid=113.CL00Y&fields=f43,f44,f45,f46,f47,f48,f60",
        "Brent": "https://push2.eastmoney.com/api/qt/stock/get?secid=113.OIL00Y&fields=f43,f44,f45,f46,f47,f48,f60",
    }
    for name, url in codes.items():
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json().get("data", {})
            if not data:
                continue
            price = data.get("f43", 0) / 100  # 东方财富价格单位是分
            prev_close = data.get("f60", 0) / 100
            if price > 0:
                result[name] = {"price": price, "prev_close": prev_close}
        except Exception as e:
            logger.warning(f"Eastmoney fetch failed for {name}: {e}")
    return result


# ── 状态持久化 ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ── 异动检测 ──────────────────────────────────────────────────────────────────

def detect_alerts(prices: dict, state: dict) -> list[str]:
    """检测异动，返回提醒列表"""
    alerts = []

    for name, data in prices.items():
        price = data["price"]
        prev_close = data.get("prev_close")

        # 日内涨跌幅
        if prev_close and prev_close > 0:
            daily_pct = (price - prev_close) / prev_close * 100
            if abs(daily_pct) >= ALERT_DAILY_CHANGE:
                direction = "📈" if daily_pct > 0 else "📉"
                alerts.append(
                    f"{direction} {name} 日内 {daily_pct:+.2f}%"
                    f"（{prev_close:.2f} → {price:.2f}）"
                )

        # 30分钟变动
        last_key = f"last_{name}"
        last_price = state.get(last_key)
        if last_price and last_price > 0:
            change_pct = (price - last_price) / last_price * 100
            if abs(change_pct) >= ALERT_CHANGE_30MIN:
                direction = "⬆️" if change_pct > 0 else "⬇️"
                alerts.append(
                    f"{direction} {name} 30分钟变动 {change_pct:+.2f}%"
                    f"（{last_price:.2f} → {price:.2f}）"
                )

    return alerts


# ── 通知 ──────────────────────────────────────────────────────────────────────

def send_alert(alerts: list[str], prices: dict):
    s = Settings()
    sender = FeishuSender(s)
    now_str = datetime.now(CN_TZ).strftime("%H:%M")

    summary_parts = []
    for name, data in prices.items():
        p = data["price"]
        pc = data.get("prev_close")
        if pc and pc > 0:
            pct = (p - pc) / pc * 100
            summary_parts.append(f"{name} ${p:.2f} ({pct:+.2f}%)")
        else:
            summary_parts.append(f"{name} ${p:.2f}")

    lines = [
        f"🛢️ 原油异动提醒 {now_str}",
        "  ".join(summary_parts),
        "",
    ] + [f"• {a}" for a in alerts]

    msg = "\n".join(lines)
    logger.info(f"Sending alert:\n{msg}")
    sender.send_text(ADMIN_OPEN_ID, msg)
    sender.send_text(GROUP_CHAT_ID, msg)


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def main():
    prices = fetch_oil_prices()
    if not prices:
        logger.warning("Failed to get oil prices, skip.")
        return

    # 日志记录当前价格
    for name, data in prices.items():
        logger.info(f"{name}: ${data['price']:.2f}")

    state = load_state()
    alerts = detect_alerts(prices, state)

    if alerts:
        send_alert(alerts, prices)
    else:
        parts = [f"{n} ${d['price']:.2f}" for n, d in prices.items()]
        logger.info(f"No anomaly. {', '.join(parts)}")

    # 更新状态
    new_state = {"last_update": datetime.now(CN_TZ).isoformat()}
    for name, data in prices.items():
        new_state[f"last_{name}"] = data["price"]
    save_state(new_state)


if __name__ == "__main__":
    main()
