"""调度器 — 轮询 Bitable 任务 → 抓取 → 分析 → 写回 → 通知"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from scraper_config import GEMINI_DAILY_LIMIT
from bitable_client import fetch_pending_tasks, update_task_status, write_result
from douyin_scraper import scrape_douyin, ScrapedVideo
from gemini_analyzer import analyze_video, get_quota

# 加载 .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def _send_feishu_notify(message: str) -> None:
    """发送飞书通知"""
    try:
        from config.settings import Settings
        from src.feishu_sender import FeishuSender
        settings = Settings()
        sender = FeishuSender(settings)
        admin_id = os.environ.get("FEISHU_ADMIN_OPEN_ID", "ou_4a18a2e35a5b04262a24f41731046d15")
        sender.send_text(admin_id, message)
    except Exception as e:
        logger.error(f"Failed to send Feishu notify: {e}")


def _build_result_fields(video: ScrapedVideo, analysis: dict, keyword: str) -> dict:
    """将抓取+分析结果组装成 Bitable 字段"""
    fields = {
        "视频标题": video.title,
        "关键词": keyword,
        "作者": video.author,
        "点赞数": video.likes,
        "评论数": video.comments,
        "视频链接": {"text": video.url, "link": video.url} if video.url else None,
    }

    if analysis:
        # 确保数字字段是 int/float
        def _safe_int(val, default=0):
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        # 确保说服机制是字符串列表
        mechanisms = analysis.get("persuasion_mechanisms", [])
        if isinstance(mechanisms, list):
            mechanisms = [str(m) for m in mechanisms]
        else:
            mechanisms = [str(mechanisms)] if mechanisms else []

        # 完整拆解截断到 10000 字符（Bitable 文本字段限制）
        full_breakdown = str(analysis.get("full_breakdown", ""))[:10000]

        fields.update({
            "Hook类型": str(analysis.get("hook_type", "其他")),
            "Hook评分": _safe_int(analysis.get("hook_score")),
            "叙事结构": str(analysis.get("narrative_structure", "其他")),
            "核心USP": str(analysis.get("core_usp", "")),
            "目标人群": str(analysis.get("target_audience", "")),
            "场景分析": str(analysis.get("scene_analysis", "")),
            "说服机制": mechanisms,
            "可复用性(1-10)": _safe_int(analysis.get("reusability_score")),
            "综合评分(1-10)": _safe_int(analysis.get("overall_score")),
            "套用建议": str(analysis.get("apply_suggestion", "")),
            "完整拆解": full_breakdown,
        })

    # 去掉 None 值
    return {k: v for k, v in fields.items() if v is not None}


def process_task(task: dict) -> dict:
    """
    处理单个任务：抓取 → 分析 → 写回

    Returns:
        {"success": int, "failed": int, "gemini_used": int}
    """
    record_id = task["record_id"]
    keyword = task["keyword"]
    count = task["count"]

    logger.info(f"=== Processing task: '{keyword}' x{count} ===")

    # 标记抓取中
    update_task_status(record_id, "抓取中")

    # Phase 2: 抓取
    videos = scrape_douyin(keyword, count)
    success_videos = [v for v in videos if v.success]

    if not success_videos:
        update_task_status(record_id, "失败", {"备注": f"抓取失败: {videos[0].error if videos else 'unknown'}"})
        return {"success": 0, "failed": len(videos), "gemini_used": 0}

    logger.info(f"Scraped {len(success_videos)}/{len(videos)} videos")

    # 标记分析中
    update_task_status(record_id, "分析中")

    # Phase 3: 分析 + 写回
    quota = get_quota()
    analyzed = 0
    failed = 0
    gemini_used = 0

    for i, video in enumerate(success_videos):
        if not quota.can_use():
            logger.warning("Gemini quota exhausted, stopping analysis")
            # 剩余视频标记为未分析
            break

        logger.info(f"Analyzing video {i + 1}/{len(success_videos)}: {video.title[:30]}...")
        analysis = analyze_video(video.video_path)
        gemini_used += 1

        # 写回 Bitable
        result_fields = _build_result_fields(video, analysis, keyword)
        rid = write_result(result_fields)
        if rid:
            analyzed += 1
            logger.info(f"Written to Bitable: {rid}")
        else:
            failed += 1

    # 更新任务状态
    total_done = analyzed
    update_task_status(record_id, "完成", {
        "已完成": total_done,
        "Gemini用量": gemini_used,
        "完成时间": int(time.time()) * 1000,  # Bitable DateTime 要毫秒
    })

    return {"success": analyzed, "failed": failed, "gemini_used": gemini_used}


def run_once() -> None:
    """单次执行：检查并处理所有待抓取任务"""
    quota = get_quota()
    logger.info(f"Gemini quota: {quota.remaining}/{GEMINI_DAILY_LIMIT} remaining")

    if not quota.can_use():
        logger.info("Gemini daily quota exhausted, skipping")
        return

    tasks = fetch_pending_tasks()
    if not tasks:
        logger.info("No pending tasks")
        return

    logger.info(f"Found {len(tasks)} pending tasks")

    total_stats = {"success": 0, "failed": 0, "gemini_used": 0}

    for task in tasks:
        # 再次检查额度
        if not quota.can_use():
            logger.warning("Gemini quota exhausted mid-run, stopping")
            break

        try:
            stats = process_task(task)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            logger.error(f"Task '{task['keyword']}' failed: {e}", exc_info=True)
            update_task_status(task["record_id"], "失败", {"备注": str(e)[:200]})
            total_stats["failed"] += 1

    # 发飞书通知
    if total_stats["success"] > 0 or total_stats["failed"] > 0:
        msg = (
            f"📹 视频抓取完成\n"
            f"成功分析: {total_stats['success']} 条\n"
            f"失败: {total_stats['failed']} 条\n"
            f"Gemini 用量: {total_stats['gemini_used']} (剩余 {quota.remaining})\n"
            f"表格: https://tcn5zi1692d5.feishu.cn/base/MnbvbQqDsaot42syrwKco3TDneg"
        )
        _send_feishu_notify(msg)
        logger.info(msg)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "once":
        run_once()
    elif mode == "loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 3600  # 默认 1 小时
        logger.info(f"Starting loop mode, interval={interval}s")
        while True:
            try:
                run_once()
            except Exception as e:
                logger.error(f"Loop iteration failed: {e}", exc_info=True)
            time.sleep(interval)
    else:
        print(f"Usage: {sys.argv[0]} [once|loop [interval_sec]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
