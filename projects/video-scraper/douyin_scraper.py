"""抖音搜索抓取 — ADB + uiautomator2 搜索关键词，scrcpy 录屏"""

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import uiautomator2 as u2

from scraper_config import (
    ADB, SCRCPY, DOUYIN_PKG, VIDEO_DIR,
    MAX_VIDEOS_PER_TASK, RECORD_BUFFER_SEC, MAX_RECORD_SEC,
)

logger = logging.getLogger(__name__)


@dataclass
class ScrapedVideo:
    """一条抓取到的视频"""
    title: str = ""
    author: str = ""
    video_path: str = ""
    duration_sec: int = 0
    likes: int = 0
    comments: int = 0
    url: str = ""
    success: bool = False
    error: str = ""


def _connect_device() -> u2.Device | None:
    """连接 ADB 设备"""
    try:
        d = u2.connect()
        info = d.info
        logger.info(f"Connected to device: {info.get('productName', 'unknown')}")
        return d
    except Exception as e:
        logger.error(f"Failed to connect device: {e}")
        return None


def _ensure_douyin_running(d: u2.Device) -> bool:
    """确保抖音在前台"""
    current = d.app_current()
    if current.get("package") != DOUYIN_PKG:
        d.app_start(DOUYIN_PKG)
        time.sleep(3)
    return d.app_current().get("package") == DOUYIN_PKG


def _open_search(d: u2.Device, keyword: str) -> bool:
    """打开抖音搜索页并输入关键词"""
    try:
        # 点击搜索图标（右上角）— 首页进入搜索页
        search_btn = d(description="搜索")
        if not search_btn.exists(timeout=3):
            # 备用：直接用坐标点击右上角搜索区域
            d.click(0.92, 0.05)
            time.sleep(1)
        else:
            search_btn.click()

        time.sleep(1.5)

        # 输入关键词（搜索框 rid = et_search_kw）
        input_box = d(resourceId="com.ss.android.ugc.aweme:id/et_search_kw")
        if not input_box.exists(timeout=3):
            input_box = d(className="android.widget.EditText")
        if input_box.exists(timeout=3):
            input_box.clear_text()
            input_box.set_text(keyword)
            time.sleep(0.5)

            # 点击搜索按钮（rid=44=）
            search_go = d(resourceId="com.ss.android.ugc.aweme:id/44=")
            if search_go.exists(timeout=2):
                search_go.click()
            else:
                d.press("enter")
            time.sleep(3)

            # 切换到"视频"tab
            video_tab = d(text="视频")
            if video_tab.exists(timeout=3):
                video_tab.click()
                time.sleep(2)

            logger.info(f"Searched for: {keyword}")
            return True

        logger.error("Search input box not found")
        return False
    except Exception as e:
        logger.error(f"Open search failed: {e}")
        return False


def _parse_count(text: str) -> int:
    """解析 '1.2万' '356' '12.5w' 格式的数字"""
    if not text:
        return 0
    text = text.strip().lower()
    text = text.replace("w", "万")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    if "亿" in text:
        try:
            return int(float(text.replace("亿", "")) * 100000000)
        except ValueError:
            return 0
    try:
        return int(re.sub(r"[^\d]", "", text))
    except ValueError:
        return 0


def _collect_video_list(d: u2.Device, count: int) -> list[dict]:
    """在搜索结果页收集视频信息（标题、点赞等）"""
    collected = []
    seen_titles = set()
    scroll_attempts = 0
    max_scrolls = count * 3

    while len(collected) < count and scroll_attempts < max_scrolls:
        # 查找视频标题（rid=desc）
        items = d(resourceId="com.ss.android.ugc.aweme:id/desc")
        if not items.exists:
            # 备用：等一下再试
            time.sleep(2)
            items = d(resourceId="com.ss.android.ugc.aweme:id/desc")

        for i in range(items.count):
            try:
                item = items[i]
                title = item.get_text() or ""
                if not title or title in seen_titles or len(title) < 4:
                    continue
                seen_titles.add(title)

                # 获取作者名（rid=+j，同层级）
                author = ""
                author_el = d(resourceId="com.ss.android.ugc.aweme:id/+j")
                if author_el.exists:
                    # 找最近的作者元素（通过 index 近似匹配）
                    for j in range(author_el.count):
                        author = author_el[j].get_text() or ""
                        if author:
                            break

                # 获取点赞数（rid=pa4，content-desc 含数字）
                likes = 0
                like_els = d(resourceId="com.ss.android.ugc.aweme:id/pa4")
                if like_els.exists and i < like_els.count:
                    desc = like_els[i].info.get("contentDescription", "")
                    # 格式: "未点赞，喜欢93，按钮"
                    m = re.search(r"喜欢(\S+?)，", desc)
                    if m:
                        likes = _parse_count(m.group(1))

                collected.append({
                    "title": title,
                    "author": author,
                    "likes": likes,
                    "index": i,
                    "bounds": item.info.get("bounds", {}),
                })
                if len(collected) >= count:
                    break
            except Exception:
                continue

        if len(collected) < count:
            d.swipe_ext("up", scale=0.5)
            time.sleep(1.5)
            scroll_attempts += 1

    logger.info(f"Collected {len(collected)} videos from search results")
    return collected[:count]


def _record_single_video(d: u2.Device, video_info: dict, keyword: str, idx: int) -> ScrapedVideo:
    """点击进入视频 → scrcpy 录屏 → 返回"""
    result = ScrapedVideo(
        title=video_info.get("title", f"video_{idx}"),
        author=video_info.get("author", ""),
        likes=video_info.get("likes", 0),
    )

    try:
        # 点击视频封面区域（bounds 来自标题元素，往上偏移点击封面）
        bounds = video_info.get("bounds", {})
        if bounds:
            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            # 标题在封面下方，往上偏移 200px 点击封面区域
            cy = max(bounds.get("top", 0) - 200, 300)
            d.click(cx, cy)
        else:
            d(text=video_info["title"]).click()

        time.sleep(3)  # 等视频加载

        # 录屏
        safe_name = re.sub(r'[^\w\-]', '_', keyword)[:20]
        output_file = VIDEO_DIR / f"{safe_name}_{idx}_{int(time.time())}.mp4"
        record_sec = min(30 + RECORD_BUFFER_SEC, MAX_RECORD_SEC)  # 默认录 38 秒

        logger.info(f"Recording video {idx}: {result.title[:30]}... ({record_sec}s)")

        proc = subprocess.run(
            [SCRCPY, "--no-playback", "--no-audio",
             f"--record={output_file}", "--max-size=720",
             f"--time-limit={record_sec}"],
            capture_output=True, text=True,
            timeout=record_sec + 15,
        )

        if output_file.exists() and output_file.stat().st_size > 100_000:
            result.video_path = str(output_file)
            result.success = True
            logger.info(f"Recorded: {output_file.name} ({output_file.stat().st_size // 1024}KB)")
        else:
            result.error = "Recording too small or failed"
            output_file.unlink(missing_ok=True)

    except subprocess.TimeoutExpired:
        result.error = "Recording timed out"
    except Exception as e:
        result.error = str(e)
        logger.error(f"Record video {idx} failed: {e}")

    # 返回搜索结果页
    d.press("back")
    time.sleep(2)

    return result


def scrape_douyin(keyword: str, count: int) -> list[ScrapedVideo]:
    """
    主入口：搜索关键词 → 收集视频列表 → 逐条录屏

    Args:
        keyword: 搜索关键词
        count: 要抓取的视频数量（上限 MAX_VIDEOS_PER_TASK）

    Returns:
        ScrapedVideo 列表
    """
    count = min(count, MAX_VIDEOS_PER_TASK)
    results: list[ScrapedVideo] = []

    d = _connect_device()
    if not d:
        return [ScrapedVideo(error="No ADB device connected")]

    if not _ensure_douyin_running(d):
        return [ScrapedVideo(error="Failed to start Douyin")]

    # 回到首页
    d.press("home")
    time.sleep(1)
    d.app_start(DOUYIN_PKG)
    time.sleep(3)

    if not _open_search(d, keyword):
        return [ScrapedVideo(error=f"Search failed for: {keyword}")]

    video_list = _collect_video_list(d, count)
    if not video_list:
        return [ScrapedVideo(error=f"No videos found for: {keyword}")]

    for idx, video_info in enumerate(video_list):
        logger.info(f"--- Scraping video {idx + 1}/{len(video_list)} ---")
        result = _record_single_video(d, video_info, keyword, idx)
        results.append(result)
        time.sleep(1)  # 短暂停歇

    logger.info(f"Scraping complete: {sum(1 for r in results if r.success)}/{len(results)} successful")
    return results
