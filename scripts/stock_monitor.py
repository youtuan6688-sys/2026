"""
东山精密 (002384) 实时异动监控
每2分钟运行一次，北京时间 9:30-15:00 交易时段内检查异动
有异动时通过飞书推送提醒
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

# ── 配置 ─────────────────────────────────────────────────────────────────────

STOCK_CODE = "sz002384"          # 东山精密
STOCK_NAME = "东山精密"
STATE_FILE = PROJECT_DIR / "data" / "stock_monitor_state.json"

# 异动触发阈值
ALERT_PRICE_CHANGE_2MIN = 1.5    # 2分钟价格变动 ≥ 1.5%
ALERT_INTRADAY_CHANGE   = 5.0    # 盘中累计涨跌幅 ≥ ±5%
ALERT_VOLUME_RATIO      = 3.0    # 当前成交量 ≥ 历史均值 3倍
ALERT_NEAR_LIMIT        = 1.0    # 距涨跌停 ≤ 1%

# 北京时区
CN_TZ = timezone(timedelta(hours=8))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── 时间判断 ──────────────────────────────────────────────────────────────────

def is_trading_time() -> bool:
    """判断当前是否是 A 股交易时段（北京时间 9:30-11:30, 13:00-15:00）"""
    now = datetime.now(CN_TZ)
    # 周末不交易
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (930 <= t <= 1130) or (1300 <= t <= 1500)


# ── 行情获取 ──────────────────────────────────────────────────────────────────

def fetch_quote() -> dict | None:
    """从新浪财经接口获取实时行情"""
    url = f"https://hq.sinajs.cn/list={STOCK_CODE}"
    headers = {"Referer": "https://finance.sina.com.cn/"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "gbk"
        raw = resp.text.strip()
        # 格式: var hq_str_sz002384="名称,开盘,昨收,现价,最高,最低,...,日期,时间,"
        data_str = raw.split('"')[1]
        if not data_str:
            logger.warning("Empty data from Sina API")
            return None
        fields = data_str.split(",")
        if len(fields) < 32:
            logger.warning(f"Unexpected field count: {len(fields)}")
            return None
        return {
            "name":         fields[0],
            "open":         float(fields[1]),
            "prev_close":   float(fields[2]),
            "price":        float(fields[3]),
            "high":         float(fields[4]),
            "low":          float(fields[5]),
            "volume":       int(fields[8]),    # 成交量（手）
            "amount":       float(fields[9]),  # 成交额（元）
            "date":         fields[30],
            "time":         fields[31],
        }
    except Exception as e:
        logger.error(f"Failed to fetch quote: {e}")
        return None


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

def detect_anomalies(quote: dict, state: dict) -> list[str]:
    """返回触发的异动描述列表"""
    alerts = []
    price = quote["price"]
    prev_close = quote["prev_close"]

    # 1. 盘中累计涨跌幅
    intraday_pct = (price - prev_close) / prev_close * 100
    if abs(intraday_pct) >= ALERT_INTRADAY_CHANGE:
        direction = "📈 上涨" if intraday_pct > 0 else "📉 下跌"
        alerts.append(f"{direction} {intraday_pct:+.2f}%（盘中累计，距涨跌停注意）")

    # 2. 接近涨跌停
    limit_up   = prev_close * 1.10
    limit_down = prev_close * 0.90
    pct_to_up   = (limit_up - price) / limit_up * 100
    pct_to_down = (price - limit_down) / price * 100
    if pct_to_up <= ALERT_NEAR_LIMIT:
        alerts.append(f"🚨 接近涨停！距涨停 {pct_to_up:.2f}%（涨停价 {limit_up:.2f}）")
    if pct_to_down <= ALERT_NEAR_LIMIT:
        alerts.append(f"🚨 接近跌停！距跌停 {pct_to_down:.2f}%（跌停价 {limit_down:.2f}）")

    # 3. 2分钟价格变动
    last_price = state.get("last_price")
    if last_price:
        price_chg_pct = (price - last_price) / last_price * 100
        if abs(price_chg_pct) >= ALERT_PRICE_CHANGE_2MIN:
            direction = "⬆️" if price_chg_pct > 0 else "⬇️"
            alerts.append(
                f"{direction} 2分钟内价格急变 {price_chg_pct:+.2f}%"
                f"（{last_price:.2f} → {price:.2f}）"
            )

    # 4. 成交量突增
    volume_history = state.get("volume_history", [])
    current_volume = quote["volume"]
    if volume_history:
        avg_vol = sum(volume_history) / len(volume_history)
        if avg_vol > 0 and current_volume >= avg_vol * ALERT_VOLUME_RATIO:
            ratio = current_volume / avg_vol
            alerts.append(
                f"🔥 成交量突增 {ratio:.1f}x"
                f"（当前 {current_volume} 手 vs 均值 {avg_vol:.0f} 手）"
            )

    return alerts


# ── 飞书通知 ──────────────────────────────────────────────────────────────────

def send_alert(alerts: list[str], quote: dict):
    settings = Settings()
    sender = FeishuSender(settings)
    owner_id = settings.feishu_user_open_id

    price = quote["price"]
    prev_close = quote["prev_close"]
    intraday_pct = (price - prev_close) / prev_close * 100
    now_cn = datetime.now(CN_TZ).strftime("%H:%M:%S")

    lines = [
        f"⚡ 东山精密 (002384) 异动提醒 {now_cn}",
        f"现价 {price:.2f}  今日 {intraday_pct:+.2f}%",
        "",
    ] + [f"• {a}" for a in alerts]

    msg = "\n".join(lines)
    logger.info(f"Sending alert:\n{msg}")
    # Send to both admin and group chat
    sender.send_text(owner_id, msg)
    group_chat_id = "oc_4f17f731a0a3bf9489c095c26be6dedc"
    sender.send_text(group_chat_id, msg)


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def main():
    if not is_trading_time():
        logger.info("Not trading hours, skip.")
        return

    quote = fetch_quote()
    if not quote:
        logger.error("Failed to get quote, abort.")
        return

    state = load_state()
    alerts = detect_anomalies(quote, state)

    if alerts:
        send_alert(alerts, quote)
    else:
        logger.info(
            f"No anomaly. {quote['name']} {quote['price']:.2f} "
            f"({(quote['price']-quote['prev_close'])/quote['prev_close']*100:+.2f}%)"
        )

    # 更新状态
    volume_history = state.get("volume_history", [])
    volume_history.append(quote["volume"])
    if len(volume_history) > 30:          # 保留最近 30 条（约1小时）
        volume_history = volume_history[-30:]

    save_state({
        "last_price": quote["price"],
        "volume_history": volume_history,
        "last_update": datetime.now(CN_TZ).isoformat(),
    })


if __name__ == "__main__":
    main()
