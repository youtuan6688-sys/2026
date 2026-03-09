"""
发送 AI管家诞生记 条漫到飞书 - 逐张发送图片+文案
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from config.settings import Settings
from src.feishu_sender import FeishuSender

PANEL_DIR = Path(__file__).parent.parent / "vault" / "comic_panels"

PANELS = [
    {"id": 1, "caption": "第1话：深夜的灵感\n\n加州深夜，程序员小T盯着屏幕，脑海中冒出一个疯狂的想法..."},
    {"id": 2, "caption": "第2话：缝合怪诞生\n\nClaude Code 做大脑，Python 当骨架，Mac Studio 做心脏——\n\n💡 别人在等AI革命，我已经在自己造了"},
    {"id": 3, "caption": "第3话：睁眼看世界\n\nAI管家「小C」正式上线！从此，小T多了一个24小时在线的超级助手"},
    {"id": 4, "caption": "第4话：十八般武艺\n\n小C的技能树全点满了：通信、分析、记忆、搜索、爬虫、下载样样精通\n\n💡 一个人 + 一个AI = 一支团队"},
    {"id": 5, "caption": "第5话：清晨侦察兵\n\n每天清晨7点（北京时间），主人还在梦乡，小C已经开始全网巡逻"},
    {"id": 6, "caption": "第6话：情报整理术\n\n海量信息涌入，小C火眼金睛筛选精华，归档到Obsidian知识库\n\n💡 信息不是力量，整理过的信息才是"},
    {"id": 7, "caption": "第7话：早安简报\n\n主人一睁眼，飞书上已经躺着一份精心准备的AI日报"},
    {"id": 8, "caption": "第8话：随叫随到\n\n不管在哪，发条飞书消息，小C秒回！解析链接、回答问题、保存笔记全搞定\n\n💡 有些人有秘书，我有AI管家，而且我的不用发工资"},
    {"id": 9, "caption": "第9话：深夜自我进化\n\n深夜人静，小C开启自我进化模式：审计知识库、学习新技能、优化流程"},
    {"id": 10, "caption": "第10话：知识就是超能力\n\n日积月累，小C建起了一座庞大的知识宝库，随时调用，无所不知\n\n💡 AI不会取代你，但有AI的你会取代没有AI的你"},
    {"id": 11, "caption": "第11话：主人和管家的日常\n\n从陌生到默契，小C越来越懂主人的习惯、偏好和工作节奏"},
    {"id": 12, "caption": "终章：未来已来\n\n这不是科幻电影，这是一个普通程序员和他的AI管家的真实故事\n\n💡 未来不是等来的，是一行一行代码敲出来的"},
]


def main():
    settings = Settings()
    sender = FeishuSender(settings)
    open_id = settings.feishu_user_open_id

    if not open_id:
        print("Error: FEISHU_USER_OPEN_ID not set in .env")
        sys.exit(1)

    # Optional: start from a specific panel
    start_from = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    print(f"Sending {len(PANELS)} comic panels to Feishu...")
    sender.send_text(open_id, "🎬 AI管家诞生记 — 条漫连载开始！\n\n一个程序员和他的AI助手的真实故事，共12话，请欣赏 👇")
    time.sleep(2)

    for panel in PANELS:
        if panel["id"] < start_from:
            continue

        image_path = PANEL_DIR / f"panel_{panel['id']:02d}.png"
        if not image_path.exists():
            print(f"  ⚠ Panel {panel['id']} not found: {image_path}")
            continue

        print(f"  [{panel['id']}/12] Sending...")

        ok = sender.send_image(open_id, str(image_path))
        if not ok:
            print(f"  ❌ Failed to send image for panel {panel['id']}")
            continue

        time.sleep(1)
        sender.send_text(open_id, panel["caption"])
        print(f"  ✅ Panel {panel['id']} sent")

        if panel["id"] < 12:
            time.sleep(2)

    sender.send_text(open_id, "🎬 完 —— 关注我，看更多AI实战故事 ❤️\n\n#AI管家 #ClaudeCode #一个人的团队")
    print("\nDone! All panels sent.")


if __name__ == "__main__":
    main()
