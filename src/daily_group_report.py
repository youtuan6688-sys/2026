"""每日群日报 — 小叼毛风格的创意群聊总结。

流水线:
1. 从 daily_buffer 提取群聊素材 (sonnet)
2. DeepSeek 写创意故事 (每天随机风格)
3. Gemini 生成 6 张配图
4. 合成发飞书群
"""

import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from config.settings import settings
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")
REPORT_DIR = Path("/Users/tuanyou/Happycode2026/data/group_reports")
GROUP_CHATS = settings.group_chat_ids

# Daily rotating writing styles
STYLES = [
    {
        "name": "起居注",
        "desc": "古风编年体，如《帝王起居注》",
        "prompt": (
            "用古代「起居注」的文体写今日群聊总结。"
            "格式如宫廷记录官，用文言夹白话，庄重中带诙谐。"
            "称呼群友为「诸卿」「某公」，bot 自称「臣（小叼毛）」。"
            "段落以时辰开头（如「辰时」「午时」），配以现代内容。"
        ),
    },
    {
        "name": "孽缘录",
        "desc": "狗血小说体",
        "prompt": (
            "用狗血网络小说的文体写今日群聊总结。"
            "标题格式「第X章：xxxx」，充满戏剧冲突和夸张修辞。"
            "群友之间的对话变成恩怨情仇，bot 是全知全能的旁白叙述者。"
            "要有经典小说金句，比如「他不知道的是，命运的齿轮已经开始转动」。"
        ),
    },
    {
        "name": "朝闻道",
        "desc": "新闻联播体",
        "prompt": (
            "用央视新闻联播的语气和格式写今日群聊总结。"
            "开头「各位群友，大家好。今天是X年X月X日，以下是本群要闻」。"
            "每条消息变成正式新闻稿，配以「据群内消息人士透露」等措辞。"
            "结尾「以上就是今天的全部内容，感谢收看，群友们再见」。"
        ),
    },
    {
        "name": "江湖周刊",
        "desc": "武侠体",
        "prompt": (
            "用武侠小说的文体写今日群聊总结。"
            "群聊变成「江湖」，群友是各路大侠，bot 是说书人。"
            "对话变成过招交手，发文件变成递暗器，@人变成飞鸽传书。"
            "要有武侠名场面的既视感，比如「此言一出，群内鸦雀无声」。"
        ),
    },
    {
        "name": "Nature 论文",
        "desc": "学术论文体",
        "prompt": (
            "用英文学术论文（Nature/Science 风格）的格式写今日群聊总结，但内容用中文。"
            "包含 Abstract、Introduction、Methods、Results、Discussion、Conclusion。"
            "群聊互动变成实验数据，emoji 变成统计指标。"
            "结尾附「参考文献」（用群友的发言做引用，格式正经）。"
        ),
    },
    {
        "name": "脱口秀稿",
        "desc": "段子手体",
        "prompt": (
            "用脱口秀演员的表演稿风格写今日群聊总结。"
            "每段一个梗，要有铺垫→反转的节奏。"
            "用第一人称（小叼毛视角），大量吐槽群友。"
            "夹带自嘲和 callback（前后呼应的笑点）。"
        ),
    },
    {
        "name": "鲁迅日记",
        "desc": "鲁迅日记体",
        "prompt": (
            "模仿鲁迅日记的文体写今日群聊总结。"
            "简洁冷峻，每句话都像在讽刺什么。"
            "格式：「X月X日，晴。上午无事。午后，某君在群内发言，甚无聊。」"
            "偶尔夹一句深刻的讽喻让人回味。"
        ),
    },
    {
        "name": "甄嬛传",
        "desc": "宫斗剧体",
        "prompt": (
            "用甄嬛传的语气和氛围写今日群聊总结。"
            "群友变成后宫嫔妃，bot 是太监总管（小叼毛公公）。"
            "说话方式「本宫」「哀家」「皇上」，暗中较劲和结盟。"
            "要有经典台词改编，比如「臣妾做不到啊→bot做不到啊」。"
        ),
    },
    {
        "name": "三体纪元",
        "desc": "科幻编年体",
        "prompt": (
            "用《三体》的纪元编年体写今日群聊总结。"
            "格式「危机纪元第X天」，群聊变成文明间的博弈。"
            "发消息 = 广播，沉默 = 暗森林状态，回复 = 维度打击。"
            "穿插三体式哲学思考，如「群聊是最好的暗森林」。"
        ),
    },
    {
        "name": "小红书种草",
        "desc": "小红书博主体",
        "prompt": (
            "用小红书博主的风格写今日群聊总结。"
            "标题要有 emoji 轰炸：「天呐❗今天群里也太好笑了吧‼️」"
            "内容分点，每点一个 emoji 开头，大量感叹号和夸张表达。"
            "结尾「姐妹们/兄弟们记得点赞关注，下期更精彩～」"
        ),
    },
]


def _load_group_entries(target_date: date | None = None) -> list[dict]:
    """Load group chat entries from daily buffer."""
    target = target_date or date.today()
    entries = []

    for f in sorted(BUFFER_DIR.glob(f"{target.isoformat()}*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("chat_type") == "group":
                    entries.append(entry)
        except Exception as e:
            logger.warning(f"Failed to read buffer {f}: {e}")

    # Also try .json files
    for f in sorted(BUFFER_DIR.glob(f"{target.isoformat()}*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries.extend(e for e in data if e.get("chat_type") == "group")
        except Exception:
            pass

    return entries


def _pick_style(target_date: date) -> dict:
    """Pick today's writing style (deterministic based on date)."""
    # Use date hash for deterministic but varied selection
    seed = int(hashlib.md5(target_date.isoformat().encode()).hexdigest(), 16)
    return STYLES[seed % len(STYLES)]


def _extract_highlights(entries: list[dict]) -> dict:
    """Extract highlights from group chat entries using Claude sonnet."""
    import subprocess

    if not entries:
        return {"quotes": [], "interactions": [], "knowledge": [],
                "new_members": [], "bot_actions": [], "summary": "今天群里比较安静"}

    # Build conversation text
    lines = []
    for e in entries[:50]:  # Cap at 50 entries
        user = e.get("user_name", e.get("sender_open_id", "?")[:8])
        msg = e.get("user_msg", "")[:300]
        reply = e.get("bot_reply", "")[:200]
        lines.append(f"{user}: {msg}")
        if reply:
            lines.append(f"  小叼毛: {reply}")

    conv_text = "\n".join(lines)

    prompt = (
        "分析以下群聊记录，提取以下素材（JSON 格式）：\n\n"
        '{"quotes": ["精华金句 top 3，原文引用"],\n'
        ' "interactions": ["有趣的互动描述，谁和谁聊了什么好玩的"],\n'
        ' "knowledge": ["今天聊到的新知识或新观点"],\n'
        ' "new_members": ["新入群成员名字"],\n'
        ' "bot_actions": ["小叼毛bot今天做了什么（分析文件/回答问题/怼人等）"],\n'
        ' "summary": "一句话总结今天群里的氛围"}\n\n'
        "规则：\n"
        "- 每个数组最多 5 条\n"
        "- quotes 保留原文，注明说话人\n"
        "- 如果群里很安静就如实说\n"
        "- 只输出 JSON，不要其他内容\n\n"
        f"群聊记录：\n{conv_text}"
    )

    try:
        env = safe_env()
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--model", "sonnet"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        output = result.stdout.strip()

        # Extract JSON
        start = output.find("{")
        end = output.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(output[start:end])
    except Exception as e:
        logger.error(f"Highlight extraction failed: {e}")

    return {"quotes": [], "interactions": [], "knowledge": [],
            "new_members": [], "bot_actions": [], "summary": "素材提取失败"}


def _build_story_prompt(highlights: dict, style: dict,
                        target_date: date) -> str:
    """Build the creative story prompt."""
    material = json.dumps(highlights, ensure_ascii=False, indent=2)
    return (
        f"你是群聊 AI 助手「小叼毛」的创意日报撰稿人。\n\n"
        f"今天的风格：【{style['name']}】— {style['desc']}\n\n"
        f"{style['prompt']}\n\n"
        f"日期：{target_date.isoformat()}\n\n"
        f"今日群聊素材：\n{material}\n\n"
        f"要求：\n"
        f"1. 必须包含以下板块（可以用风格化标题）：\n"
        f"   - 精华金句 TOP 3\n"
        f"   - Bot 自我进化/任务完成记录\n"
        f"   - 群友有趣互动\n"
        f"   - 新知识速递（如果有）\n"
        f"   - 新成员报到（如果有）\n"
        f"   - 小叼毛第一人称总结/碎碎念\n"
        f"2. 800-1200字\n"
        f"3. 有趣、有可读性、高品质\n"
        f"4. 风格要到位，不要半途而废\n"
        f"5. 如果素材少，就脑补发挥，但注明是虚构\n\n"
        f"直接输出正文，不要元说明。"
    )


def _write_story(highlights: dict, style: dict,
                 target_date: date) -> str:
    """Write creative story — phone DeepSeek app (free) first, API fallback."""
    prompt = _build_story_prompt(highlights, style, target_date)

    # Try phone DeepSeek app first (free, via uiautomator2)
    try:
        import importlib.util
        _phone_ai_path = Path(__file__).parent.parent / "devices" / "oppo-PDYM20" / "scripts" / "phone_ai.py"
        _spec = importlib.util.spec_from_file_location("phone_ai", _phone_ai_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        PhoneAI, DEEPSEEK = _mod.PhoneAI, _mod.DEEPSEEK
        ai = PhoneAI()
        story = ai.generate_content(prompt, app=DEEPSEEK)
        if story and len(story) > 100:
            logger.info(f"Story generated via phone DeepSeek app ({len(story)} chars)")
            return story
        logger.warning(f"Phone DeepSeek returned too short: {len(story)} chars")
    except Exception as e:
        logger.warning(f"Phone DeepSeek failed, falling back to API: {e}")

    # Fallback: DeepSeek API
    try:
        resp = httpx.post(
            f"{settings.ai_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            json={
                "model": settings.ai_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 3000,
                "temperature": 0.9,
            },
            timeout=90,
        )
        resp.raise_for_status()
        logger.info("Story generated via DeepSeek API (fallback)")
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"DeepSeek API also failed: {e}")
        return f"[日报生成失败: {e}]"


def _build_image_prompts(style: dict) -> list[str]:
    """Build 6 scene prompts for image generation."""
    return [
        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景1：一个可爱的机器人吉祥物（小叼毛）在大屏幕上阅读群聊消息。"
        f"温暖多彩的氛围，高品质插画。",

        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景2：群聊成员们热烈讨论，对话气泡四处飞舞。"
        f"动感构图，鲜艳色彩，高品质。",

        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景3：机器人吉祥物用巨大的羽毛笔书写今日精华。"
        f"闪光效果，创意氛围，高品质。",

        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景4：今日精华金句展示在金色卷轴上。"
        f"优雅的排版感，装饰边框，高品质。",

        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景5：机器人吉祥物正在进化升级，发光效果。"
        f"变身场景，能量粒子，高品质。",

        f"生成一张可爱的卡通插画，Q版动漫风格，{style['name']}主题。"
        f"场景6：结尾画面——机器人吉祥物挥手告别。"
        f"夕阳/傍晚氛围，温暖感人，高品质。",
    ]


def _generate_images(story: str, style: dict,
                     target_date: date) -> list[Path]:
    """Generate 6 images — phone Gemini app (free) first, API fallback."""
    output_dir = REPORT_DIR / target_date.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_prompts = _build_image_prompts(style)

    # Try phone Gemini app first (free, via uiautomator2)
    try:
        import importlib.util
        _gemini_path = Path(__file__).parent.parent / "devices" / "oppo-PDYM20" / "scripts" / "gemini_image.py"
        _spec = importlib.util.spec_from_file_location("gemini_image", _gemini_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        GeminiImageGenerator = _mod.GeminiImageGenerator
        gen = GeminiImageGenerator()
        images = []
        for i, prompt in enumerate(scene_prompts):
            filename = f"scene_{i + 1}.png"
            result = gen.generate_and_download(prompt, filename)
            if result and result.exists():
                # Copy to output_dir
                import shutil
                dest = output_dir / filename
                shutil.copy2(result, dest)
                images.append(dest)
                logger.info(f"Generated image {i + 1}/6 via phone Gemini")
            else:
                logger.warning(f"Phone Gemini: image {i + 1} failed")
        if images:
            return images
        logger.warning("Phone Gemini returned no images")
    except Exception as e:
        logger.warning(f"Phone Gemini failed, falling back to API: {e}")

    # Fallback: Gemini API
    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai not installed, skipping image generation")
        return []

    api_key = settings.gemini_api_key
    if not api_key:
        logger.warning("No Gemini API key, skipping image generation")
        return []

    client = genai.Client(api_key=api_key)
    images = []
    for i, prompt in enumerate(scene_prompts):
        try:
            response = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config={"number_of_images": 1},
            )
            if response.generated_images:
                img_path = output_dir / f"scene_{i + 1}.png"
                img_data = response.generated_images[0].image.image_bytes
                img_path.write_bytes(img_data)
                images.append(img_path)
                logger.info(f"Generated image {i + 1}/6 via API")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"API image {i + 1} failed: {e}")

    return images


def _send_report(story: str, images: list[Path], style: dict,
                 target_date: date):
    """Send the daily report to group chats via Feishu."""
    from src.feishu_sender import FeishuSender

    sender = FeishuSender(settings)

    header = f"📰 小叼毛日报 [{target_date.isoformat()}] — 「{style['name']}」风格\n\n"
    full_text = header + story

    for chat_id in GROUP_CHATS:
        # Send text report
        sender.send_text(chat_id, full_text)

        # Send images
        for img_path in images:
            try:
                sender.send_file(chat_id, str(img_path))
            except Exception as e:
                logger.warning(f"Failed to send image {img_path.name}: {e}")

    logger.info(f"Daily report sent to {len(GROUP_CHATS)} groups")


def _save_report(story: str, highlights: dict, style: dict,
                 target_date: date):
    """Save report to vault for archival."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"{target_date.isoformat()}.md"

    content = (
        f"# 小叼毛日报 [{target_date.isoformat()}]\n\n"
        f"风格: {style['name']} — {style['desc']}\n\n"
        f"## 素材\n\n"
        f"```json\n{json.dumps(highlights, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 正文\n\n{story}\n"
    )
    report_file.write_text(content, encoding="utf-8")
    logger.info(f"Report saved to {report_file}")


def generate_daily_report(target_date: date | None = None):
    """Main entry point: generate and send the daily group report."""
    target = target_date or date.today()
    logger.info(f"=== Generating Daily Group Report for {target} ===")

    # 1. Load group entries
    entries = _load_group_entries(target)
    logger.info(f"Loaded {len(entries)} group entries")

    if not entries:
        logger.info("No group entries today, skipping report")
        return

    # 2. Pick today's style
    style = _pick_style(target)
    logger.info(f"Today's style: {style['name']} — {style['desc']}")

    # 3. Extract highlights (sonnet)
    highlights = _extract_highlights(entries)
    logger.info(f"Extracted highlights: {len(highlights.get('quotes', []))} quotes, "
                f"{len(highlights.get('interactions', []))} interactions")

    # 4. Write creative story (DeepSeek)
    story = _write_story(highlights, style, target)
    logger.info(f"Story generated: {len(story)} chars")

    # 5. Generate images (Gemini)
    images = _generate_images(story, style, target)
    logger.info(f"Generated {len(images)} images")

    # 6. Save report
    _save_report(story, highlights, style, target)

    # 7. Send to groups
    _send_report(story, images, style, target)

    logger.info("=== Daily Group Report Complete ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    target = date.today()
    if len(sys.argv) > 1 and sys.argv[1] == "yesterday":
        target = date.today() - timedelta(days=1)

    generate_daily_report(target)
