"""Gemini 视频分析模块 — 视频理解 + 结构化拆解"""

import json
import logging
import os
import time
from pathlib import Path

import google.generativeai as genai

from scraper_config import GEMINI_MODEL, GEMINI_DAILY_LIMIT, GEMINI_RPM, QUOTA_FILE

logger = logging.getLogger(__name__)

# 初始化
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

ANALYSIS_PROMPT = """你是一位爆款视频分析专家。请对这个视频进行深度拆解分析。

## 分析要求

### 场景分析三维度（必须遵循）
1. **色调**: 暖色调 / 冷色调 / 促销热情色调 / 暧昧氛围感色调
2. **物理空间**: 直播间 / 办公室 / 户外商场 / 居家场景 / 工厂车间 / 摄影棚 / 街拍
3. **镜头语言**: 半身 / 怼脸直拍 / 全身 / 半身+产品特写 / 怼脸直拍+产品特写

### 输出 JSON 格式（严格遵循）
```json
{
  "hook_type": "悬念开场/痛点开场/反常识开场/数据开场/利益开场/情景开场/其他",
  "hook_score": 8,
  "narrative_structure": "AIDA/PAS/礼物堆叠+紧迫/故事型/教程型/其他",
  "core_usp": "核心卖点一句话",
  "target_audience": "目标人群描述",
  "scene_analysis": "色调(具体描述) | 物理空间 | 镜头语言",
  "persuasion_mechanisms": ["FOMO", "锚定效应"],
  "reusability_score": 8,
  "overall_score": 8,
  "apply_suggestion": "如何套用这个视频的结构",
  "full_breakdown": "逐3-5秒的详细拆解（时间段 → 画面 → 口播 → 情绪 → 营销功能）"
}
```

只输出 JSON，不要其他文字。"""


class QuotaTracker:
    """Gemini 每日额度追踪"""

    def __init__(self):
        self._load()

    def _load(self) -> None:
        if QUOTA_FILE.exists():
            data = json.loads(QUOTA_FILE.read_text())
            today = time.strftime("%Y-%m-%d")
            if data.get("date") == today:
                self.used = data.get("used", 0)
                self.date = today
                return
        self.used = 0
        self.date = time.strftime("%Y-%m-%d")
        self._save()

    def _save(self) -> None:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(json.dumps({
            "date": self.date,
            "used": self.used,
            "limit": GEMINI_DAILY_LIMIT,
        }))

    def can_use(self, count: int = 1) -> bool:
        today = time.strftime("%Y-%m-%d")
        if today != self.date:
            self.used = 0
            self.date = today
        return self.used + count <= GEMINI_DAILY_LIMIT

    def consume(self, count: int = 1) -> None:
        self.used += count
        self._save()

    @property
    def remaining(self) -> int:
        return max(0, GEMINI_DAILY_LIMIT - self.used)


_quota = QuotaTracker()
_last_call_time = 0.0


def get_quota() -> QuotaTracker:
    return _quota


def analyze_video(video_path: str) -> dict | None:
    """
    用 Gemini 分析视频文件，返回结构化结果。

    Args:
        video_path: 本地视频文件路径

    Returns:
        解析后的 dict 或 None（失败时）
    """
    global _last_call_time

    if not _quota.can_use():
        logger.warning(f"Gemini daily quota exhausted ({_quota.used}/{GEMINI_DAILY_LIMIT})")
        return None

    path = Path(video_path)
    if not path.exists():
        logger.error(f"Video file not found: {video_path}")
        return None

    # 速率限制
    elapsed = time.time() - _last_call_time
    min_interval = 60.0 / GEMINI_RPM
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

    try:
        logger.info(f"Uploading video to Gemini: {path.name} ({path.stat().st_size // 1024}KB)")

        # 上传视频文件
        video_file = genai.upload_file(str(path), mime_type="video/mp4")

        # 等待文件处理完成
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name != "ACTIVE":
            logger.error(f"Video processing failed: {video_file.state.name}")
            return None

        # 调用模型分析
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            [video_file, ANALYSIS_PROMPT],
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=8192,
            ),
        )

        _last_call_time = time.time()
        _quota.consume()

        # 解析 JSON
        text = response.text.strip()
        # 去掉可能的 markdown code fence
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        if text.startswith("json"):
            text = text[4:]

        result = json.loads(text.strip())
        logger.info(f"Analysis complete: score={result.get('overall_score')}, "
                     f"quota={_quota.used}/{GEMINI_DAILY_LIMIT}")

        # 清理上传的文件
        try:
            genai.delete_file(video_file.name)
        except Exception:
            pass

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        _quota.consume()  # still counts
        return None
    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return None
