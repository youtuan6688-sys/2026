"""Video analysis using Gemini 2.0 Flash — native video understanding (frames + audio)."""

import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from src.video.models import VideoInfo, BreakdownResult

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
PROMPT_PATH = Path("/Users/tuanyou/Happycode2026/projects/viral-video-analyzer/prompts/video_breakdown.md")
TREND_PROMPT_PATH = Path("/Users/tuanyou/Happycode2026/projects/viral-video-analyzer/prompts/trend_analysis.md")

# Gemini File API: free tier 2GB storage, files expire after 48h
MAX_UPLOAD_SIZE_MB = 100
UPLOAD_TIMEOUT = 120


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    # Fallback minimal prompt
    return (
        "你是短视频内容策略师。分析这个视频的 hook、结构、视觉、音频、文案，"
        "输出 JSON 格式的拆解报告，包含 overall_score 和 one_sentence_summary。"
    )


def _load_trend_prompt() -> str:
    if TREND_PROMPT_PATH.exists():
        return TREND_PROMPT_PATH.read_text(encoding="utf-8")
    return "分析以下视频拆解数据的趋势，输出 JSON。"


def analyze_video(info: VideoInfo) -> BreakdownResult:
    """Upload video to Gemini and run breakdown analysis.

    If video_path is empty (download failed), falls back to metadata-only analysis.
    """
    result = BreakdownResult(
        url=info.url,
        platform=info.platform,
        title=info.title,
    )

    try:
        client = _get_client()
        prompt = _load_prompt()

        # Build metadata context
        metadata_text = _format_metadata(info)

        if info.video_path and Path(info.video_path).exists():
            # Full analysis: upload video + metadata
            breakdown = _analyze_with_video(client, info.video_path, prompt, metadata_text)
        else:
            # Fallback: metadata-only analysis
            logger.info(f"No video file, falling back to metadata analysis: {info.url}")
            breakdown = _analyze_metadata_only(client, prompt, metadata_text)

        result.breakdown_json = breakdown
        result.summary = breakdown.get("one_sentence_summary", "")
        score = breakdown.get("overall_score", {})
        result.total_score = score.get("total", 0) if isinstance(score, dict) else 0
        result.video_info = {
            "title": info.title, "author": info.author,
            "platform": info.platform, "duration": info.duration,
            "views": info.views, "likes": info.likes,
        }

    except Exception as e:
        logger.error(f"Video analysis failed: {e}", exc_info=True)
        result.error = str(e)

    return result


def _analyze_with_video(client: genai.Client, video_path: str,
                        prompt: str, metadata: str) -> dict:
    """Upload video via File API, then analyze with Gemini."""
    logger.info(f"Uploading video to Gemini: {video_path}")

    # Upload file
    video_file = client.files.upload(
        file=video_path,
        config=types.UploadFileConfig(display_name=Path(video_path).name),
    )

    # Wait for processing
    _wait_for_file_active(client, video_file)

    logger.info(f"Video uploaded: {video_file.name}, analyzing...")

    user_prompt = f"{prompt}\n\n## 视频元数据\n{metadata}\n\n请输出 JSON 格式的拆解报告。只输出 JSON，不要其他文字。"

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(
                        file_uri=video_file.uri,
                        mime_type=video_file.mime_type,
                    ),
                    types.Part.from_text(text=user_prompt),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=8192,
        ),
    )

    # Clean up uploaded file
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass  # Files auto-expire in 48h

    return _parse_json_response(response.text)


def _analyze_metadata_only(client: genai.Client, prompt: str, metadata: str) -> dict:
    """Analyze using only metadata (no video file)."""
    user_prompt = (
        f"{prompt}\n\n## 视频元数据\n{metadata}\n\n"
        "注意：没有视频文件，仅基于元数据分析。视觉和音频维度请标注为「⚠️ 无视频，基于推测」。\n"
        "请输出 JSON 格式的拆解报告。只输出 JSON，不要其他文字。"
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=8192,
        ),
    )

    return _parse_json_response(response.text)


def analyze_trends(breakdowns: list[dict]) -> dict:
    """Analyze trends from accumulated breakdown results."""
    client = _get_client()
    prompt = _load_trend_prompt()

    data_text = json.dumps(breakdowns, ensure_ascii=False, indent=1)
    # Truncate if too long
    if len(data_text) > 30000:
        data_text = data_text[:30000] + "\n... (truncated)"

    user_prompt = f"{prompt}\n\n## 拆解数据\n{data_text}\n\n请输出 JSON。只输出 JSON，不要其他文字。"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=8192,
        ),
    )

    return _parse_json_response(response.text)


def _format_metadata(info: VideoInfo) -> str:
    parts = []
    if info.title:
        parts.append(f"标题: {info.title}")
    if info.author:
        parts.append(f"作者: {info.author}")
    if info.platform:
        parts.append(f"平台: {info.platform}")
    if info.duration:
        parts.append(f"时长: {info.duration}秒")
    if info.views:
        parts.append(f"播放量: {info.views:,}")
    if info.likes:
        parts.append(f"点赞: {info.likes:,}")
    if info.comments:
        parts.append(f"评论: {info.comments:,}")
    if info.shares:
        parts.append(f"分享: {info.shares:,}")
    if info.description:
        parts.append(f"描述: {info.description[:500]}")
    if info.publish_date:
        parts.append(f"发布日期: {info.publish_date}")
    return "\n".join(parts)


def _wait_for_file_active(client: genai.Client, file_ref, max_wait: int = 120):
    """Poll until the uploaded file is in ACTIVE state."""
    for _ in range(max_wait // 5):
        f = client.files.get(name=file_ref.name)
        if f.state.name == "ACTIVE":
            return
        if f.state.name == "FAILED":
            raise RuntimeError(f"File processing failed: {file_ref.name}")
        time.sleep(5)
    raise TimeoutError(f"File not active after {max_wait}s: {file_ref.name}")


def _parse_json_response(text: str) -> dict:
    """Extract JSON from Gemini response (handles markdown code fences)."""
    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON from Gemini response: {text[:200]}")
        return {"raw_response": text, "parse_error": True}
