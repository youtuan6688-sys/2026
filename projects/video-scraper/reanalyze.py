"""重分析脚本 — 将已下载的视频重新用 Gemini 分析并写入 V3 Bitable"""

import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import requests

from scraper_config import VIDEO_DIR, GEMINI_DAILY_LIMIT, BITABLE_APP_TOKEN, RESULT_TABLE_ID, LARK_API_BASE
from bitable_client import write_result, write_breakdown_rows, ensure_owner_access, _headers
from gemini_analyzer import analyze_video, get_quota

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _build_result_fields(video_path: Path, analysis: dict, keyword: str) -> dict:
    """组装 Bitable 字段"""
    fields = {
        "视频标题": f"{keyword}_{video_path.stem}",
        "关键词": keyword,
        "作者": "待补充",
    }

    if analysis:
        def _safe_int(val, default=0):
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        mechanisms = analysis.get("persuasion_mechanisms", [])
        if isinstance(mechanisms, list):
            mechanisms = [str(m) for m in mechanisms]
        else:
            mechanisms = [str(mechanisms)] if mechanisms else []

        full_breakdown = str(analysis.get("full_breakdown", ""))[:10000]

        usp = str(analysis.get("core_usp", ""))
        summary = str(analysis.get("one_sentence_summary", ""))
        if summary and summary != usp:
            usp = f"{usp}\n\n爆款原因：{summary}"

        scene = str(analysis.get("scene_analysis", ""))
        audio = str(analysis.get("audio_analysis", ""))
        if audio:
            scene = f"{scene}\n\n音频：{audio}"

        suggestion = str(analysis.get("apply_suggestion", ""))
        copywriting = str(analysis.get("copywriting_highlights", ""))
        hook_detail = str(analysis.get("hook_detail", ""))
        if hook_detail:
            suggestion = f"Hook分析：{hook_detail}\n\n{suggestion}"
        if copywriting:
            suggestion = f"{suggestion}\n\n文案亮点：{copywriting}"

        fields.update({
            "Hook类型": str(analysis.get("hook_type", "其他")),
            "Hook评分": _safe_int(analysis.get("hook_score")),
            "叙事结构": str(analysis.get("narrative_structure", "其他")),
            "核心USP": usp,
            "目标人群": str(analysis.get("target_audience", "")),
            "场景分析": scene,
            "说服机制": mechanisms,
            "可复用性(1-10)": _safe_int(analysis.get("reusability_score")),
            "综合评分(1-10)": _safe_int(analysis.get("overall_score")),
            "套用建议": suggestion,
            "完整拆解": full_breakdown,
        })

    return {k: v for k, v in fields.items() if v is not None}


def _build_breakdown_rows(analysis: dict, video_title: str, keyword: str) -> list[dict]:
    """将 timeline 转为逐秒拆解行"""
    timeline = analysis.get("timeline", [])
    if not timeline:
        return []

    rows = []
    for entry in timeline:
        row = {
            "时间段": str(entry.get("time", "")),
            "视频标题": video_title,
            "关键词": keyword,
            "场景(色调|空间)": str(entry.get("scene", "")),
            "角色": str(entry.get("character", "")),
            "产品": str(entry.get("product", "")),
            "口播": str(entry.get("voiceover", "")),
            "字幕文案": str(entry.get("subtitle", "")),
            "画面描述": str(entry.get("visual_desc", "")),
            "镜头语言": str(entry.get("camera", "其他")),
            "情绪节奏": str(entry.get("emotion", "其他")),
            "说服机制": [str(m) for m in entry.get("persuasion", [])] if isinstance(entry.get("persuasion"), list) else [],
            "营销功能": str(entry.get("marketing_function", "其他")),
        }
        rows.append(row)
    return rows


def get_best_videos() -> dict[str, list[Path]]:
    """按关键词分组，每组取最大的文件（最完整的录屏）"""
    videos: dict[str, list[Path]] = {}
    for f in sorted(VIDEO_DIR.glob("*.mp4")):
        # 文件名格式: {keyword}_{idx}_{timestamp}.mp4
        parts = f.stem.split("_")
        if len(parts) >= 3:
            keyword = parts[0]
            idx = parts[1]
            key = f"{keyword}_{idx}"  # 同一关键词+序号可能有多个版本
            if key not in videos:
                videos[key] = []
            videos[key].append(f)

    # 每组取最大文件（最完整的录屏）
    best: dict[str, list[Path]] = {}
    for key, files in videos.items():
        keyword = key.split("_")[0]
        biggest = max(files, key=lambda f: f.stat().st_size)
        # 跳过太小的文件（< 1MB，可能是失败的录屏）
        if biggest.stat().st_size < 1024 * 1024:
            logger.warning(f"Skipping small file: {biggest.name} ({biggest.stat().st_size // 1024}KB)")
            continue
        if keyword not in best:
            best[keyword] = []
        best[keyword].append(biggest)

    return best


def _get_analyzed_titles() -> set[str]:
    """从 Bitable 获取已分析的视频标题，用于去重"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{RESULT_TABLE_ID}/records/search"
    try:
        resp = requests.post(url, headers=_headers(), json={"field_names": ["视频标题"]}, timeout=15)
        data = resp.json()
        titles = set()
        for item in data.get("data", {}).get("items", []):
            title_val = item.get("fields", {}).get("视频标题", "")
            if isinstance(title_val, list):
                title_val = "".join(t.get("text", "") for t in title_val if isinstance(t, dict))
            if title_val:
                titles.add(title_val)
        return titles
    except Exception as e:
        logger.error(f"Failed to fetch existing titles: {e}")
        return set()


def main():
    ensure_owner_access()

    quota = get_quota()
    logger.info(f"Gemini quota: {quota.remaining}/{GEMINI_DAILY_LIMIT} remaining")

    # 获取已分析的视频标题用于去重
    analyzed_titles = _get_analyzed_titles()
    logger.info(f"Already analyzed: {len(analyzed_titles)} videos")

    best_videos = get_best_videos()
    total_videos = sum(len(v) for v in best_videos.values())
    logger.info(f"Found {total_videos} videos across {len(best_videos)} keywords: {list(best_videos.keys())}")

    if not quota.can_use(total_videos):
        logger.warning(f"Not enough quota for {total_videos} videos (remaining: {quota.remaining})")

    success = 0
    failed = 0

    for keyword, video_files in best_videos.items():
        logger.info(f"\n=== Keyword: {keyword} ({len(video_files)} videos) ===")

        for video_path in video_files:
            if not quota.can_use():
                logger.warning("Quota exhausted, stopping")
                break

            video_title = f"{keyword}_{video_path.stem}"
            if video_title in analyzed_titles:
                logger.info(f"Skipping already analyzed: {video_path.name}")
                continue

            logger.info(f"Analyzing: {video_path.name} ({video_path.stat().st_size // 1024}KB)")
            analysis = analyze_video(str(video_path))

            if not analysis:
                logger.error(f"Analysis failed for {video_path.name}")
                failed += 1
                continue

            result_fields = _build_result_fields(video_path, analysis, keyword)
            rid = write_result(result_fields)

            if rid:
                success += 1
                logger.info(f"Written result: {rid} (score={analysis.get('overall_score')})")

                breakdown_rows = _build_breakdown_rows(analysis, video_title, keyword)
                if breakdown_rows:
                    written = write_breakdown_rows(breakdown_rows, parent_record_id=rid)
                    logger.info(f"Written {written} breakdown rows")
            else:
                failed += 1
                logger.error(f"Failed to write result for {video_path.name}")

    logger.info(f"\n=== Done: {success} success, {failed} failed, quota remaining: {quota.remaining} ===")


if __name__ == "__main__":
    main()
