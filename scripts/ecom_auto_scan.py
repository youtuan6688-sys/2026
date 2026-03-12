#!/usr/bin/env python3
"""Auto-scan e-commerce bitable records and generate AI content.

Designed to run as a cron job. Scans configured bitable tables for
records with empty AI fields and processes them automatically.

Usage:
    python scripts/ecom_auto_scan.py [--app-token TOKEN] [--dry-run]

Configuration via environment:
    ECOM_BITABLE_APP_TOKEN — bitable app token to scan
    (Also reads .env via config/settings.py for AI API keys)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.feishu_bitable import FeishuBitableManager
from src.feishu_sender import FeishuSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ecom_auto_scan")

# AI prompts for auto-processing — same as EcomHandler.FIELD_PROMPTS
FIELD_PROMPTS = {
    "天猫文案": (
        "根据以下产品描述，写一段天猫/淘宝详情页文案（300-500字），"
        "要求专业、信任背书、卖点突出。直接输出文案，不要 JSON。\n\n产品信息：{content}"
    ),
    "小红书文案": (
        "根据以下产品描述，写一篇小红书种草笔记（200-400字），"
        "要求生活化、有共鸣、软种草，带 emoji 和话题标签。直接输出文案。\n\n产品信息：{content}"
    ),
    "抖音脚本": (
        "根据以下产品描述，写一个 55-65 秒的抖音口播脚本，"
        "包含钩子（前3秒）、痛点、解决方案、行动号召。直接输出脚本。\n\n产品信息：{content}"
    ),
    "投流文案": (
        "根据以下产品描述，写 3 条投流广告文案（每条≤50字），"
        "要求卖点前置、强CTA。直接输出 3 条，换行分隔。\n\n产品信息：{content}"
    ),
    "极限词检测": (
        "检测以下文案中的广告法违禁词/极限词。"
        "输出格式：\n违规词 → 建议替换\n如无违规，输出「合规，无违禁词」。\n\n文案：{content}"
    ),
}

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", settings.feishu_app_id)


def run_scan(app_token: str, dry_run: bool = False) -> dict:
    """Scan and process bitable records.

    Returns: {"processed": int, "failed": int, "skipped": int}
    """
    bm = FeishuBitableManager(settings)

    app_token = bm.extract_app_token(app_token)
    tables = bm.list_tables(app_token)
    if not tables:
        logger.error("No tables found")
        return {"processed": 0, "failed": 0, "skipped": 0}

    # Find product table
    table_id = None
    for t in tables:
        if "商品" in t["name"] or "产品" in t["name"]:
            table_id = t["table_id"]
            logger.info(f"Found table: {t['name']} ({table_id})")
            break
    if not table_id:
        table_id = tables[0]["table_id"]
        logger.info(f"Using first table: {tables[0]['name']} ({table_id})")

    if dry_run:
        # Just count records
        result = bm.list_records(app_token, table_id, page_size=100)
        records = result["records"]
        needs_processing = sum(
            1 for r in records
            if r["fields"].get("产品描述") and not r["fields"].get("天猫文案")
        )
        logger.info(f"Dry run: {needs_processing} records need processing out of {len(records)}")
        return {"processed": 0, "failed": 0, "skipped": needs_processing}

    stats = bm.ai_process_batch(
        app_token, table_id,
        source_field="产品描述",
        target_fields=FIELD_PROMPTS,
        filter_field="天猫文案",
        max_records=20,
    )

    logger.info(f"Scan complete: {stats}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="E-commerce bitable auto-scan")
    parser.add_argument("--app-token", default=os.getenv("ECOM_BITABLE_APP_TOKEN", ""),
                        help="Bitable app token or URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count records without processing")
    parser.add_argument("--notify", action="store_true",
                        help="Send results to admin via Feishu")
    args = parser.parse_args()

    if not args.app_token:
        logger.error("No app token. Set ECOM_BITABLE_APP_TOKEN or use --app-token")
        sys.exit(1)

    stats = run_scan(args.app_token, dry_run=args.dry_run)

    if args.notify and not args.dry_run and stats["processed"] > 0:
        try:
            sender = FeishuSender(settings)
            sender.send_text(
                ADMIN_CHAT_ID,
                f"电商 AI 自动扫描完成\n"
                f"  处理: {stats['processed']} 条\n"
                f"  失败: {stats['failed']} 条\n"
                f"  跳过: {stats['skipped']} 条\n"
                f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    # Log result
    log_path = PROJECT_ROOT / "logs" / "ecom_scan.log"
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "app_token": args.app_token,
            "dry_run": args.dry_run,
            **stats,
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
