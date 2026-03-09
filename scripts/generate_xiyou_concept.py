"""
大话西游 赛博朋克概念图生成器
风格：机甲修真 + 赛博佛陀 + 虚幻5引擎渲染质感
"""

import base64
import io
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from PIL import Image

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "nano-banana-pro-preview"
OUTPUT_DIR = Path(__file__).parent.parent / "vault" / "xiyou_concept"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=API_KEY)

# 概念图：探索风格感觉
CONCEPTS = [
    {
        "id": 1,
        "name": "monkey_king_mech",
        "title": "齐天大圣·机甲战神",
        "prompt": (
            "Cinematic Unreal Engine 5 rendered image, hyperrealistic 8K quality, "
            "Sun Wukong the Monkey King in a massive cyberpunk mech suit. "
            "The mech is inspired by ancient Chinese armor but fully mechanical — "
            "golden titanium alloy plating, glowing jade-green energy cores, "
            "neon-lit runes engraved on the surface, extending mechanical staff weapon. "
            "His face is partially visible through a cracked helmet visor, eyes glowing with golden fire. "
            "Background: dystopian futuristic floating mountain fortress in neon-lit night sky, "
            "electric storms, Buddha silhouettes projected in clouds. "
            "Dramatic cinematic lighting, volumetric fog, lens flares. "
            "Style: Cyberpunk 2077 meets Black Myth Wukong meets Ghost of Tsushima. "
            "Photorealistic game CG quality, epic composition, wide angle hero shot."
        ),
    },
    {
        "id": 2,
        "name": "cyber_buddha",
        "title": "赛博佛陀·数字涅槃",
        "prompt": (
            "Cinematic Unreal Engine 5 rendered image, hyperrealistic 8K quality, "
            "A colossal Cyber Buddha deity, half organic ancient statue half quantum machine. "
            "Body made of obsidian black metal with glowing golden circuit board patterns. "
            "A thousand mechanical arms extending with holographic data streams and laser weapons. "
            "The face serene but eyes emit neon blue laser beams. "
            "Surrounded by floating Sanskrit code characters as data particles. "
            "Sitting in lotus position on a mechanical lotus throne above clouds. "
            "Background: apocalyptic future city below, stars visible through atmospheric haze. "
            "Color palette: deep black, neon gold, electric blue, blood red accents. "
            "God-tier scale, intimidating, awe-inspiring. Photorealistic game CG, Unreal Engine 5."
        ),
    },
    {
        "id": 3,
        "name": "tang_monk_pilot",
        "title": "唐僧·机甲圣僧",
        "prompt": (
            "Cinematic Unreal Engine 5 rendered image, hyperrealistic 8K quality, "
            "Tang Sanzang (the Tang Monk) as a cyberpunk mech pilot-priest hybrid. "
            "Wearing white and gold mechanical monk robes fused with powered exosuit armor. "
            "Holographic sutra scrolls floating around him displaying divine code. "
            "Mechanical prayer beads that are actually server nodes connected by light cables. "
            "Serene expression, glowing halo made of fiber optic cables. "
            "Background: Neon-soaked cyberpunk city street at rain, ancient temple ruins visible. "
            "Dramatic cinematic portrait, shallow depth of field. "
            "Style: Blade Runner 2049 aesthetic with Eastern mythology. "
            "Photorealistic, volumetric light rays, rain particles, Unreal Engine 5 quality."
        ),
    },
    {
        "id": 4,
        "name": "group_shot",
        "title": "西天取经·机甲战队",
        "prompt": (
            "Cinematic Unreal Engine 5 rendered image, hyperrealistic 8K quality, "
            "Epic group hero shot: the Journey to the West team in cyberpunk mech suits, "
            "standing on the edge of a cliff overlooking a neon megacity. "
            "Sun Wukong: golden simian mech with cloud-riding boosters and staff. "
            "Zhu Bajie: heavy pig-themed brawler mech with demolition hammer, fat and powerful. "
            "Sha Wujing: sleek water-element mech with monk spade cannon on shoulder. "
            "Tang Sanzang: elegant white prophet mech glowing with divine data. "
            "All four mechs in different poses, team assembled, facing the horizon. "
            "Golden sunset behind neon city skyline, Buddha moon in the sky. "
            "Epic cinematic wide shot, rule of thirds, dramatic lighting. "
            "Style: Avengers End Game group shot meets Black Myth Wukong aesthetic. "
            "Photorealistic game CG, Unreal Engine 5, 8K resolution."
        ),
    },
]


def generate_concept(concept: dict) -> Image.Image | None:
    """Generate a single concept image using Gemini."""
    prompt = concept["prompt"]

    for attempt in range(3):
        try:
            print(f"  Generating: {concept['title']} (attempt {attempt+1})")
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    img_bytes = part.inline_data.data
                    img = Image.open(io.BytesIO(img_bytes))
                    return img

            print(f"  Warning: No image in response")
            if attempt < 2:
                time.sleep(5)

        except Exception as e:
            print(f"  Error: {e}")
            if attempt < 2:
                time.sleep(10)

    return None


def main():
    # Support generating specific concept by ID
    target_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    concepts = [c for c in CONCEPTS if target_id is None or c["id"] == target_id]

    print("=" * 60)
    print("🎨 大话西游·赛博机甲 - 概念图探索")
    print(f"📝 生成 {len(concepts)} 张概念图")
    print("=" * 60)

    for concept in concepts:
        print(f"\n[{concept['id']}/{len(CONCEPTS)}] {concept['title']}")
        img = generate_concept(concept)

        if img is None:
            print(f"  ❌ 生成失败，跳过")
            continue

        # Save
        output_path = OUTPUT_DIR / f"{concept['id']:02d}_{concept['name']}.png"
        img.save(output_path)
        print(f"  ✅ 保存到: {output_path}")

        if concept["id"] < concepts[-1]["id"]:
            print("  ⏳ 等待 8s 避免限流...")
            time.sleep(8)

    print(f"\n🎉 完成！图片保存在: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
