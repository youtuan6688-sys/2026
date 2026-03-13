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

# 抖音 resource ID 前缀
_RID = "com.ss.android.ugc.aweme:id/"


@dataclass
class CommentData:
    """一条评论"""
    username: str = ""
    content: str = ""
    likes: int = 0
    time: str = ""
    location: str = ""
    is_author: bool = False
    replies: list = field(default_factory=list)  # list[CommentData]


@dataclass
class ScrapedVideo:
    """一条抓取到的视频"""
    title: str = ""
    author: str = ""
    video_path: str = ""
    duration_sec: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    bookmarks: int = 0
    url: str = ""
    publish_date: str = ""
    top_comments: list = field(default_factory=list)  # list[CommentData]
    success: bool = False
    error: str = ""


def _connect_device() -> u2.Device | None:
    """连接 ADB 设备，唤醒屏幕"""
    try:
        d = u2.connect()
        d.screen_on()
        time.sleep(1)
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


def _open_search(d: u2.Device, keyword: str, time_filter: str = "") -> bool:
    """打开抖音搜索页并输入关键词，可选时间筛选"""
    try:
        # 点击搜索图标（右上角）— 首页进入搜索页
        search_btn = d(description="搜索")
        if not search_btn.exists(timeout=3):
            d.click(0.92, 0.05)
            time.sleep(1)
        else:
            search_btn.click()

        time.sleep(1.5)

        # 输入关键词（搜索框 rid = et_search_kw）
        input_box = d(resourceId=f"{_RID}et_search_kw")
        if not input_box.exists(timeout=3):
            input_box = d(className="android.widget.EditText")
        if input_box.exists(timeout=3):
            input_box.clear_text()
            input_box.set_text(keyword)
            time.sleep(0.5)

            # 点击搜索按钮（rid=44=）
            search_go = d(resourceId=f"{_RID}44=")
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

            # 应用时间筛选
            if time_filter:
                _apply_time_filter(d, time_filter)

            logger.info(f"Searched for: {keyword}" + (f" (filter: {time_filter})" if time_filter else ""))
            return True

        logger.error("Search input box not found")
        return False
    except Exception as e:
        logger.error(f"Open search failed: {e}")
        return False


def _apply_time_filter(d: u2.Device, time_filter: str) -> None:
    """在搜索结果页应用时间筛选"""
    # 抖音搜索筛选实际选项：不限 / 一天内 / 一周内 / 半年内
    filter_map = {
        "1d": "一天内",
        "7d": "一周内",
        "30d": "半年内",   # 抖音没有"月"选项，用半年内代替
        "90d": "半年内",
        "180d": "半年内",
    }
    label = filter_map.get(time_filter)
    if not label:
        return

    try:
        # 点击"筛选"按钮（desc 可能是"筛选"或"筛选有新消息"）
        filter_btn = d(descriptionContains="筛选")
        if not filter_btn.exists(timeout=2):
            filter_btn = d(text="筛选")
        if filter_btn.exists(timeout=2):
            filter_btn.click()
            time.sleep(1)

            # 选择时间范围
            time_option = d(text=label)
            if time_option.exists(timeout=2):
                time_option.click()
                time.sleep(1)

                # 点击筛选按钮关闭面板（抖音没有确定按钮）
                filter_btn_close = d(descriptionContains="筛选")
                if filter_btn_close.exists(timeout=1):
                    filter_btn_close.click()
                    time.sleep(2)
                else:
                    d.press("back")
                    time.sleep(2)
                logger.info(f"Applied time filter: {label}")
            else:
                logger.warning(f"Time filter option '{label}' not found")
                # 关闭面板
                d.press("back")
                time.sleep(1)
        else:
            logger.warning("Filter button not found")
    except Exception as e:
        logger.warning(f"Time filter failed: {e}")


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


def _extract_desc_count(desc: str, keyword: str) -> int:
    """从 contentDescription 中提取数字，如 '喜欢1056' → 1056"""
    m = re.search(rf"{keyword}(\S+?)，", desc)
    if m:
        return _parse_count(m.group(1))
    # 备用：直接找数字
    m = re.search(rf"{keyword}(\d[\d.]*[万亿w]?)", desc)
    if m:
        return _parse_count(m.group(1))
    return 0


def _collect_video_list(d: u2.Device, count: int) -> list[dict]:
    """在搜索结果页收集视频信息（标题、点赞等）"""
    collected = []
    seen_titles = set()
    scroll_attempts = 0
    max_scrolls = count * 3

    while len(collected) < count and scroll_attempts < max_scrolls:
        # 查找视频标题（rid=desc）
        items = d(resourceId=f"{_RID}desc")
        if not items.exists:
            time.sleep(2)
            items = d(resourceId=f"{_RID}desc")

        for i in range(items.count):
            try:
                item = items[i]
                title = item.get_text() or ""
                if not title or title in seen_titles or len(title) < 4:
                    continue
                seen_titles.add(title)

                # 获取作者名（rid=+j，同层级）
                author = ""
                author_el = d(resourceId=f"{_RID}+j")
                if author_el.exists:
                    for j in range(author_el.count):
                        author = author_el[j].get_text() or ""
                        if author:
                            break

                # 获取点赞数（rid=pa4，content-desc 含数字）
                likes = 0
                like_els = d(resourceId=f"{_RID}pa4")
                if like_els.exists and i < like_els.count:
                    desc = like_els[i].info.get("contentDescription", "")
                    likes = _extract_desc_count(desc, "喜欢")

                # 获取发布时间（rid=3v=，如"2025.09.28"或"昨天19:00"）
                publish_date = ""
                date_els = d(resourceId=f"{_RID}3v=")
                if date_els.exists and i < date_els.count:
                    publish_date = date_els[i].get_text() or ""

                collected.append({
                    "title": title,
                    "author": author,
                    "likes": likes,
                    "publish_date": publish_date,
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


def _extract_video_detail(d: u2.Device, result: ScrapedVideo) -> None:
    """在视频详情页提取互动数据、发布时间、视频链接"""
    try:
        # 点赞数（rid=gkp, desc="未点赞，喜欢N，按钮"）
        like_el = d(resourceId=f"{_RID}gkp")
        if like_el.exists(timeout=2):
            desc = like_el.info.get("contentDescription", "")
            result.likes = _extract_desc_count(desc, "喜欢")

        # 评论数（rid=et7, desc="评论N，按钮"）
        comment_el = d(resourceId=f"{_RID}et7")
        if comment_el.exists:
            desc = comment_el.info.get("contentDescription", "")
            result.comments = _extract_desc_count(desc, "评论")

        # 收藏数（rid=d-c, desc="未选中，收藏N，按钮"）
        bookmark_el = d(resourceId=f"{_RID}d-c")
        if bookmark_el.exists:
            desc = bookmark_el.info.get("contentDescription", "")
            result.bookmarks = _extract_desc_count(desc, "收藏")

        # 分享/转发数（rid=zs-, desc="分享N，按钮"）
        share_el = d(resourceId=f"{_RID}zs-")
        if share_el.exists:
            desc = share_el.info.get("contentDescription", "")
            result.shares = _extract_desc_count(desc, "分享")

        # 发布时间（rid=4uy, desc="发布时间：XX月XX日"）
        time_el = d(resourceId=f"{_RID}4uy")
        if time_el.exists:
            desc = time_el.info.get("contentDescription", "")
            if "发布时间" in desc:
                result.publish_date = desc.replace("发布时间：", "").strip()
            else:
                result.publish_date = time_el.get_text().strip().lstrip(" ·").strip()

        logger.info(f"Detail: likes={result.likes} comments={result.comments} "
                     f"bookmarks={result.bookmarks} shares={result.shares} "
                     f"date={result.publish_date}")

    except Exception as e:
        logger.warning(f"Extract detail failed: {e}")


def _extract_video_url(d: u2.Device, result: ScrapedVideo) -> None:
    """通过分享→复制链接获取视频 URL，带重试"""
    for attempt in range(2):
        try:
            share_btn = d(resourceId=f"{_RID}zs-")
            if not share_btn.exists(timeout=2):
                logger.warning("Share button not found")
                return

            share_btn.click()
            time.sleep(2)

            # 找"复制链接"或"分享链接"按钮
            share_link = d(text="复制链接")
            if not share_link.exists(timeout=2):
                share_link = d(text="分享链接")
            if not share_link.exists(timeout=1):
                # 滑动分享面板到右边查找
                d.swipe(900, 2200, 200, 2200, 0.3)
                time.sleep(1)
                share_link = d(text="复制链接")
                if not share_link.exists(timeout=1):
                    share_link = d(text="分享链接")

            if share_link.exists(timeout=1):
                share_link.click()
                time.sleep(2)

                # 从剪贴板读取 URL
                clipboard = ""
                try:
                    clipboard = d.clipboard or ""
                except Exception:
                    # 备用：用 adb 读剪贴板
                    try:
                        import subprocess as _sp
                        clip_out = _sp.run(
                            [ADB, "shell", "am", "broadcast", "-a", "clipper.get"],
                            capture_output=True, text=True, timeout=5,
                        )
                        clipboard = clip_out.stdout or ""
                    except Exception:
                        pass

                url_match = re.search(r"https?://\S+", clipboard)
                if url_match:
                    result.url = url_match.group(0).rstrip("/").rstrip(")")
                    logger.info(f"Got URL: {result.url}")
                    # 关闭可能的提示面板
                    d.press("back")
                    time.sleep(1)
                    return
                else:
                    logger.warning(f"No URL in clipboard (attempt {attempt+1}): {clipboard[:100]}")

                d.press("back")
                time.sleep(1)
            else:
                logger.warning(f"Copy link button not found (attempt {attempt+1})")
                d.press("back")
                time.sleep(1)

        except Exception as e:
            logger.warning(f"Extract URL failed (attempt {attempt+1}): {e}")
            d.press("back")
            time.sleep(1)


def _scrape_top_comments(d: u2.Device, top_n: int = 5) -> list[CommentData]:
    """打开评论区，抓取 TOP N 高赞评论及子回复"""
    comments = []
    try:
        comment_btn = d(resourceId=f"{_RID}et7")
        if not comment_btn.exists(timeout=2):
            return comments

        comment_btn.click()
        time.sleep(2)

        # 收集评论（默认按热度排序）
        seen_contents = set()
        scroll_attempts = 0

        while len(comments) < top_n and scroll_attempts < 3:
            # 找所有评论容器 (rid=fa6)
            comment_containers = d(resourceId=f"{_RID}fa6")
            if not comment_containers.exists:
                break

            for i in range(comment_containers.count):
                if len(comments) >= top_n:
                    break
                try:
                    container = comment_containers[i]
                    container_desc = container.info.get("contentDescription", "")

                    # 跳过已处理的
                    if container_desc in seen_contents:
                        continue
                    seen_contents.add(container_desc)

                    # 在容器内找用户名和内容
                    # 用 contentDescription 解析（格式：用户名,内容,时间,地区,回复 按钮,）
                    parts = container_desc.split(",")
                    if len(parts) < 2:
                        continue

                    comment = CommentData(
                        username=parts[0].strip(),
                        content=parts[1].strip() if len(parts) > 1 else "",
                    )

                    # 时间和地区
                    if len(parts) > 2:
                        comment.time = parts[2].strip()
                    if len(parts) > 3:
                        loc = parts[3].strip()
                        if loc.startswith("· "):
                            loc = loc[2:]
                        comment.location = loc

                    # 作者标记
                    if "作者" in container_desc:
                        comment.is_author = True

                    # 跳过空内容
                    if not comment.content:
                        continue

                    # 找该评论的点赞数（gj5, desc="赞N,未选中"）
                    like_els = d(resourceId=f"{_RID}gj5")
                    if like_els.exists and i < like_els.count:
                        like_desc = like_els[i].info.get("contentDescription", "")
                        m = re.search(r"赞(\d+)", like_desc)
                        if m:
                            comment.likes = int(m.group(1))

                    comments.append(comment)

                except Exception:
                    continue

            if len(comments) < top_n:
                # 滚动评论区看更多
                d.swipe(540, 2000, 540, 1200, 0.3)
                time.sleep(1)
                scroll_attempts += 1

        # 关闭评论区
        close_btn = d(resourceId=f"{_RID}back_btn")
        if close_btn.exists:
            close_btn.click()
        else:
            d.press("back")
        time.sleep(1)

        logger.info(f"Scraped {len(comments)} comments")

    except Exception as e:
        logger.warning(f"Scrape comments failed: {e}")
        d.press("back")
        time.sleep(1)

    return comments


def _record_single_video(d: u2.Device, video_info: dict, keyword: str, idx: int) -> ScrapedVideo:
    """点击进入视频 → 提取详情 → 获取链接 → scrcpy 录屏 → 抓评论 → 返回"""
    result = ScrapedVideo(
        title=video_info.get("title", f"video_{idx}"),
        author=video_info.get("author", ""),
        likes=video_info.get("likes", 0),
        publish_date=video_info.get("publish_date", ""),
    )

    try:
        # 点击视频封面区域（bounds 来自标题元素，往上偏移点击封面）
        bounds = video_info.get("bounds", {})
        if bounds:
            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            cy = max(bounds.get("top", 0) - 200, 300)
            d.click(cx, cy)
        else:
            d(text=video_info["title"]).click()

        time.sleep(3)  # 等视频加载

        # Step 1: 提取详情页互动数据
        _extract_video_detail(d, result)

        # Step 2: 获取视频链接
        _extract_video_url(d, result)

        # Step 3: 录屏
        safe_name = re.sub(r'[^\w\-]', '_', keyword)[:20]
        output_file = VIDEO_DIR / f"{safe_name}_{idx}_{int(time.time())}.mp4"
        record_sec = min(30 + RECORD_BUFFER_SEC, MAX_RECORD_SEC)

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

        # Step 4: 抓取高赞评论
        result.top_comments = _scrape_top_comments(d)

    except subprocess.TimeoutExpired:
        result.error = "Recording timed out"
    except Exception as e:
        result.error = str(e)
        logger.error(f"Record video {idx} failed: {e}")

    # 返回搜索结果页
    d.press("back")
    time.sleep(2)

    return result


def scrape_douyin(keyword: str, count: int, time_filter: str = "") -> list[ScrapedVideo]:
    """
    主入口：搜索关键词 → 收集视频列表 → 逐条录屏+分析

    Args:
        keyword: 搜索关键词
        count: 要抓取的视频数量（上限 MAX_VIDEOS_PER_TASK）
        time_filter: 时间筛选（"7d"/"30d"/"90d"/"180d"/""）

    Returns:
        ScrapedVideo 列表
    """
    count = min(count, MAX_VIDEOS_PER_TASK)
    results: list[ScrapedVideo] = []

    d = _connect_device()
    if not d:
        return [ScrapedVideo(error="No ADB device connected")]

    # 强制停止 + 冷启动抖音，确保回到首页（避免残留在搜索结果页）
    try:
        subprocess.run([ADB, "shell", "am", "force-stop", DOUYIN_PKG],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    time.sleep(2)

    # 重新确认 u2 连接可用（force-stop 可能影响 UIAutomator2）
    try:
        d.info  # 测试连接
    except Exception:
        logger.warning("u2 connection lost after force-stop, reconnecting...")
        d = u2.connect()
        d.screen_on()
        time.sleep(1)

    d.app_start(DOUYIN_PKG)
    time.sleep(5)

    # 等待首页加载完成（搜索按钮出现）
    search_ready = d(description="搜索").exists(timeout=5)
    if not search_ready:
        # 可能弹了广告/更新弹窗，尝试关掉
        d.press("back")
        time.sleep(2)

    if not _open_search(d, keyword, time_filter):
        return [ScrapedVideo(error=f"Search failed for: {keyword}")]

    video_list = _collect_video_list(d, count)
    if not video_list:
        return [ScrapedVideo(error=f"No videos found for: {keyword}")]

    for idx, video_info in enumerate(video_list):
        logger.info(f"--- Scraping video {idx + 1}/{len(video_list)} ---")
        result = _record_single_video(d, video_info, keyword, idx)
        results.append(result)
        time.sleep(1)

    logger.info(f"Scraping complete: {sum(1 for r in results if r.success)}/{len(results)} successful")
    return results
