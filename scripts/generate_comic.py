"""
AI管家诞生记 - 条漫生成脚本
用 Gemini Nano Banana Pro 生成多面板中文条漫，拼接后发飞书
"""

import base64
import io
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageDraw, ImageFont

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "nano-banana-pro-preview"
OUTPUT_DIR = Path(__file__).parent.parent / "vault" / "comic_panels"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=API_KEY)

# ============================================================
# 条漫故事脚本 - 12 面板
# ============================================================
PANELS = [
    {
        "id": 1,
        "title": "第1话：深夜的灵感",
        "prompt": (
            "Cute cartoon style, a young Chinese programmer sitting alone in a home office late at night "
            "in California. Moonlight through window, multiple monitors glowing, coffee cups everywhere. "
            "He has a thought bubble showing a cute robot. Chinese text on screen: 'AI管家计划'. "
            "Warm cozy atmosphere, anime style illustration. Speech bubble in Chinese: '如果我有一个永不睡觉的AI助手...'"
        ),
        "caption": "加州深夜，程序员小T盯着屏幕，脑海中冒出一个疯狂的想法...",
        "quote": "",
    },
    {
        "id": 2,
        "title": "第2话：缝合怪诞生",
        "prompt": (
            "Cute cartoon style, a dramatic creation scene. A programmer typing furiously on keyboard, "
            "code flying around him like magic. Icons floating: Python snake, Claude AI logo, Mac Studio computer, "
            "gears and lightning bolts. A cute baby robot emerging from the code with sparkling eyes. "
            "Chinese text banner: 'Claude Code + Python + Mac Studio = ?'. Colorful, energetic, anime style."
        ),
        "caption": "Claude Code 做大脑，Python 当骨架，Mac Studio 做心脏——",
        "quote": "💡 金句：别人在等AI革命，我已经在自己造了",
    },
    {
        "id": 3,
        "title": "第3话：睁眼看世界",
        "prompt": (
            "Cute cartoon style, a adorable small robot opening its eyes for the first time, "
            "surrounded by sparkles and light beams. The robot is cute, round, with big eyes and a small antenna. "
            "A programmer kneeling next to it like a proud parent. Speech bubble from robot in Chinese: "
            "'主人好！我是小C，你的AI管家！' Background is a cozy tech office. Heartwarming scene, anime style."
        ),
        "caption": "AI管家「小C」正式上线！从此，小T多了一个24小时在线的超级助手",
        "quote": "",
    },
    {
        "id": 4,
        "title": "第4话：十八般武艺",
        "prompt": (
            "Cute cartoon infographic style, a cute robot in the center surrounded by 6 floating skill icons "
            "in a circle: 1) chat bubble (飞书通信), 2) brain with gears (AI分析), 3) book (知识库), "
            "4) globe with magnifying glass (全网搜索), 5) spider web (网页爬虫), 6) video play button (视频下载). "
            "Each icon has a small Chinese label. Robot looks proud with arms akimbo. Colorful, flat design, anime style."
        ),
        "caption": "小C的技能树全点满了：通信、分析、记忆、搜索、爬虫、下载样样精通",
        "quote": "💡 金句：一个人 + 一个AI = 一支团队",
    },
    {
        "id": 5,
        "title": "第5话：清晨侦察兵",
        "prompt": (
            "Cute cartoon style, split scene: left side shows a cute robot at a desk with multiple floating "
            "news screens and web browsers, reading AI news eagerly with a detective hat. Right side shows the "
            "programmer sleeping peacefully in bed with a 'Zzz' bubble. Clock shows 7:00 AM. "
            "Chinese text: '主人还在睡，小C已经开始工作了'. Dawn sky through window. Anime style, warm colors."
        ),
        "caption": "每天清晨7点（北京时间），主人还在梦乡，小C已经开始全网巡逻",
        "quote": "",
    },
    {
        "id": 6,
        "title": "第6话：情报整理术",
        "prompt": (
            "Cute cartoon style, a cute robot sitting at a desk organizing colorful cards and documents. "
            "Cards labeled: 'Claude新功能', 'AI行业动态', 'GitHub热门项目'. The robot uses a magic wand to "
            "sort them into neat folders labeled '知识库'. Sparkles and organization lines. "
            "Speech bubble: '这条重要！这条也要收藏！' Anime style, bright cheerful colors."
        ),
        "caption": "海量信息涌入，小C火眼金睛筛选精华，归档到Obsidian知识库",
        "quote": "💡 金句：信息不是力量，整理过的信息才是",
    },
    {
        "id": 7,
        "title": "第7话：早安简报",
        "prompt": (
            "Cute cartoon style, a programmer waking up, stretching, picking up phone with a smile. "
            "Phone screen shows a beautiful formatted morning briefing with charts and bullet points. "
            "The cute robot is shown in a small bubble on the phone waving. Chinese text on phone: "
            "'☀️ 早安！今日AI圈大事'. Sunshine through window, coffee on nightstand. Warm morning atmosphere, anime style."
        ),
        "caption": "主人一睁眼，飞书上已经躺着一份精心准备的AI日报",
        "quote": "",
    },
    {
        "id": 8,
        "title": "第8话：随叫随到",
        "prompt": (
            "Cute cartoon style, a dynamic scene showing the programmer in different situations: "
            "at cafe, walking, at desk - all sending messages on phone. The cute robot appears as a "
            "hologram from the phone each time, helping with different tasks: analyzing a webpage, "
            "answering questions, saving notes. Chinese speech bubbles: '帮我分析这个链接', '收到！马上处理'. "
            "Multiple action panels, energetic anime style."
        ),
        "caption": "不管在哪，发条飞书消息，小C秒回！解析链接、回答问题、保存笔记全搞定",
        "quote": "💡 金句：有些人有秘书，我有AI管家，而且我的不用发工资",
    },
    {
        "id": 9,
        "title": "第9话：深夜自我进化",
        "prompt": (
            "Cute cartoon style, nighttime scene. The cute robot sitting in a meditation pose, "
            "surrounded by floating code symbols, books, and glowing upgrade icons. Its body is "
            "slightly glowing with energy. Background shows a starry sky through window. "
            "Text floating around: '学习新技能', '优化记忆', '更新知识'. "
            "Mystical and peaceful atmosphere. Chinese text: '夜深了，是小C升级的时间'. Anime style."
        ),
        "caption": "深夜人静，小C开启自我进化模式：审计知识库、学习新技能、优化流程",
        "quote": "",
    },
    {
        "id": 10,
        "title": "第10话：知识就是超能力",
        "prompt": (
            "Cute cartoon style, the cute robot standing triumphantly on a mountain of organized books "
            "and digital files. It holds a glowing orb labeled '知识库' above its head. Around it, "
            "holographic screens show statistics: '500+ articles', '1000+ memories'. "
            "The programmer stands nearby looking impressed with stars in eyes. "
            "Epic pose, superhero-like composition. Chinese banner: '知识就是超能力'. Anime style."
        ),
        "caption": "日积月累，小C建起了一座庞大的知识宝库，随时调用，无所不知",
        "quote": "💡 金句：AI不会取代你，但有AI的你会取代没有AI的你",
    },
    {
        "id": 11,
        "title": "第11话：主人和管家的日常",
        "prompt": (
            "Cute cartoon style, a heartwarming montage of daily scenes between the programmer and "
            "the cute robot: sharing morning coffee (robot holds tiny cup), celebrating completing a project "
            "(high five), the robot reminding the programmer to take a break. "
            "Warm golden hour lighting, cozy atmosphere. Small hearts floating around. "
            "Chinese text: '最好的搭档，是懂你的那一个'. Anime style, emotional."
        ),
        "caption": "从陌生到默契，小C越来越懂主人的习惯、偏好和工作节奏",
        "quote": "",
    },
    {
        "id": 12,
        "title": "终章：未来已来",
        "prompt": (
            "Cute cartoon style, epic final panel. The programmer and cute robot standing side by side "
            "on a cliff, looking at a sunrise over a futuristic city skyline. Robot on programmer's shoulder. "
            "Both silhouetted against the golden sunrise. Flying cars and holographic screens in the city. "
            "Large Chinese text overlay: '未来已来，我们准备好了'. "
            "Inspirational, cinematic composition, anime style. Dramatic lighting."
        ),
        "caption": "这不是科幻电影，这是一个普通程序员和他的AI管家的真实故事",
        "quote": "💡 金句：未来不是等来的，是一行一行代码敲出来的",
    },
]


def generate_panel(panel: dict) -> Image.Image | None:
    """Generate a single comic panel using Gemini."""
    prompt = (
        f"Create a high quality vertical comic panel illustration. "
        f"Style: cute Japanese anime/manga, vibrant colors, clean lines, suitable for social media. "
        f"Scene: {panel['prompt']} "
        f"Important: Include Chinese text clearly and legibly where specified. "
        f"The image should be vertical format (portrait orientation), 1024x1280 pixels."
    )

    for attempt in range(3):
        try:
            print(f"  Generating panel {panel['id']}... (attempt {attempt+1})")
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            # Extract image from response
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    img_bytes = part.inline_data.data
                    img = Image.open(io.BytesIO(img_bytes))
                    return img

            print(f"  Warning: No image in response for panel {panel['id']}")
            if attempt < 2:
                time.sleep(5)

        except Exception as e:
            print(f"  Error panel {panel['id']}: {e}")
            if attempt < 2:
                time.sleep(10)

    return None


def add_text_overlay(img: Image.Image, panel: dict) -> Image.Image:
    """Add caption and quote text below the image panel."""
    # Create a new image with space for text below
    text_height = 180 if panel["quote"] else 120
    new_width = img.width
    new_height = img.height + text_height

    canvas = Image.new("RGB", (new_width, new_height), "white")
    canvas.paste(img, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # Try to load a Chinese font
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    font = None
    font_sm = None
    font_quote = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 28)
                font_sm = ImageFont.truetype(fp, 24)
                font_quote = ImageFont.truetype(fp, 26)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()
        font_sm = font
        font_quote = font

    # Draw title bar
    title_y = img.height + 10
    draw.rectangle([(20, title_y), (new_width - 20, title_y + 40)], fill="#FF6B6B")
    draw.text((30, title_y + 5), panel["title"], fill="white", font=font)

    # Draw caption
    caption_y = title_y + 50
    # Word wrap caption
    caption = panel["caption"]
    max_chars = (new_width - 60) // 24  # approximate
    lines = []
    while len(caption) > max_chars:
        lines.append(caption[:max_chars])
        caption = caption[max_chars:]
    lines.append(caption)
    for i, line in enumerate(lines):
        draw.text((30, caption_y + i * 30), line, fill="#333333", font=font_sm)

    # Draw quote if present
    if panel["quote"]:
        quote_y = caption_y + len(lines) * 30 + 10
        draw.text((30, quote_y), panel["quote"], fill="#FF6B6B", font=font_quote)

    return canvas


def stitch_comic(panels: list[Image.Image]) -> Image.Image:
    """Stitch all panels vertically into a single long comic strip."""
    # Normalize all panels to same width
    target_width = 1080  # Good for mobile/social media

    resized = []
    for p in panels:
        ratio = target_width / p.width
        new_h = int(p.height * ratio)
        resized.append(p.resize((target_width, new_h), Image.LANCZOS))

    # Add spacing between panels
    spacing = 20
    total_height = sum(p.height for p in resized) + spacing * (len(resized) - 1) + 200  # +200 for header/footer

    comic = Image.new("RGB", (target_width, total_height), "#FFF5F5")
    draw = ImageDraw.Draw(comic)

    # Header
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    title_font = None
    subtitle_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                title_font = ImageFont.truetype(fp, 48)
                subtitle_font = ImageFont.truetype(fp, 28)
                break
            except Exception:
                continue

    # Draw header
    draw.rectangle([(0, 0), (target_width, 100)], fill="#FF6B6B")
    if title_font:
        draw.text((target_width // 2 - 200, 20), "🤖 AI管家诞生记", fill="white", font=title_font)
    if subtitle_font:
        draw.text((target_width // 2 - 180, 75), "一个程序员和他的AI助手的真实故事", fill="#FFE0E0", font=subtitle_font)

    y_offset = 120
    for i, panel in enumerate(resized):
        comic.paste(panel, (0, y_offset))
        y_offset += panel.height + spacing

    # Footer
    if subtitle_font:
        draw.text((target_width // 2 - 160, y_offset + 10), "关注我，看更多AI实战故事 ❤️", fill="#FF6B6B", font=subtitle_font)

    return comic


def main():
    # Support resuming from a specific panel via CLI arg
    start_from = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print("=" * 50)
    print("🎨 AI管家诞生记 - 条漫生成器")
    print(f"📝 共 {len(PANELS)} 个面板, 从第 {start_from} 话开始")
    print("=" * 50)

    generated_panels = []

    # Load already-generated panels
    for panel in PANELS:
        if panel["id"] < start_from:
            existing = OUTPUT_DIR / f"panel_{panel['id']:02d}.png"
            if existing.exists():
                print(f"  ✅ Loading existing panel {panel['id']}: {existing}")
                generated_panels.append(Image.open(existing))
            continue

    for panel in [p for p in PANELS if p["id"] >= start_from]:
        print(f"\n[{panel['id']}/{len(PANELS)}] {panel['title']}")
        img = generate_panel(panel)

        if img is None:
            print(f"  ❌ Failed to generate panel {panel['id']}, skipping")
            continue

        # Save raw panel
        raw_path = OUTPUT_DIR / f"panel_{panel['id']:02d}_raw.png"
        img.save(raw_path)
        print(f"  ✅ Raw saved: {raw_path}")

        # Add text overlay
        final = add_text_overlay(img, panel)
        final_path = OUTPUT_DIR / f"panel_{panel['id']:02d}.png"
        final.save(final_path)
        print(f"  ✅ Final saved: {final_path}")

        generated_panels.append(final)

        # Rate limiting
        if panel["id"] < len(PANELS):
            print("  ⏳ Waiting 5s for rate limit...")
            time.sleep(5)

    if not generated_panels:
        print("\n❌ No panels generated!")
        sys.exit(1)

    print(f"\n🧵 Stitching {len(generated_panels)} panels into comic strip...")
    comic = stitch_comic(generated_panels)

    # Save full comic
    comic_path = Path(__file__).parent.parent / "vault" / "ai_butler_comic.png"
    comic.save(comic_path, quality=95)
    print(f"✅ Comic saved: {comic_path}")

    # Also save as JPEG for smaller file size (better for social media)
    comic_jpg = Path(__file__).parent.parent / "vault" / "ai_butler_comic.jpg"
    comic_rgb = comic.convert("RGB")
    comic_rgb.save(comic_jpg, "JPEG", quality=90)
    print(f"✅ JPEG saved: {comic_jpg}")

    # Also save individual panels as separate images (for carousel posts)
    print(f"\n📱 Individual panels saved in: {OUTPUT_DIR}")
    print(f"   (Use these for carousel/swipe posts on Xiaohongshu)")

    print(f"\n🎉 Done! Generated {len(generated_panels)} panels")
    print(f"   Full comic: {comic_path}")
    print(f"   Individual panels: {OUTPUT_DIR}/panel_*.png")


if __name__ == "__main__":
    main()
