"""
小红书自动发布模块
通过 ADB + uiautomator2 操控手机小红书 App
完成：选图 → 填标题 → 填正文 → 发布/存草稿
"""

import uiautomator2 as u2
import time
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

XHS_PKG = "com.xingin.xhs"


@dataclass(frozen=True)
class XhsNote:
    """小红书笔记内容"""
    title: str
    body: str
    image_path: str      # 手机上的图片路径（/sdcard/...）
    hashtags: list[str]   # 话题标签（不含 #）


class XhsPublisher:
    """通过 ADB 操控小红书 App 发布笔记"""

    def __init__(self, serial: str | None = None):
        self.device = u2.connect(serial)
        logger.info(f"连接设备: {self.device.info.get('productName', 'unknown')}")

    def screenshot(self, name: str) -> Path:
        path = Path(f"/tmp/xhs_{name}_{int(time.time())}.png")
        self.device.screenshot(str(path))
        return path

    def open_xhs(self) -> None:
        self.device.app_start(XHS_PKG)
        time.sleep(4)
        logger.info("小红书已打开")

    def go_home(self) -> None:
        """确保在首页"""
        home = self.device(description="首页")
        if home.exists(timeout=3):
            home.click()
            time.sleep(1)

    def start_publish(self) -> None:
        """点击发布按钮，进入相册选择"""
        self.device(description="发布").click()
        time.sleep(2)

        # 选择"从相册选择"
        album = self.device(text="从相册选择")
        if album.exists(timeout=3):
            album.click()
            time.sleep(3)
            logger.info("进入相册选择")

    def select_latest_image(self, index: int = 0) -> None:
        """选择相册中的图片（默认最新的第一张）

        Args:
            index: 图片索引，0=最新，1=第二新...按网格从左到右、从上到下排列
        """
        # 网格布局: 3列，每张约 354x354
        col = index % 3
        row = index // 3
        x = 177 + col * 363  # 每列中心 x
        y = 554 + row * 363  # 第一行中心 y=554
        self.device.click(x, y)
        time.sleep(2)
        logger.info(f"选择第 {index + 1} 张图片 (row={row}, col={col})")

    def next_step(self) -> None:
        """点击下一步"""
        btn = self.device(text="下一步")
        if btn.exists(timeout=3):
            btn.click()
            time.sleep(3)
            logger.info("下一步")

    def fill_note(self, note: XhsNote) -> None:
        """填写标题和正文"""
        # 输入标题
        title_box = self.device(text="添加标题")
        if title_box.exists(timeout=3):
            title_box.click()
            time.sleep(0.5)
            title_box.set_text(note.title)
            time.sleep(0.5)
            logger.info(f"标题: {note.title}")

        # 输入正文（拼接 hashtag）
        body_with_tags = note.body
        if note.hashtags:
            tags = " ".join(f"#{tag}" for tag in note.hashtags)
            body_with_tags = f"{note.body}\n\n{tags}"

        body_box = self.device(text="添加正文或发语音")
        if body_box.exists(timeout=3):
            body_box.click()
            time.sleep(0.5)
            body_box.set_text(body_with_tags)
            time.sleep(0.5)
            logger.info(f"正文: {len(body_with_tags)} 字")

        # 收起键盘
        self.device.press("back")
        time.sleep(1)

    def publish(self) -> bool:
        """点击发布笔记"""
        btn = self.device(text="发布笔记")
        if btn.exists(timeout=3):
            btn.click()
            time.sleep(5)
            logger.info("✅ 笔记已发布")
            return True
        logger.error("未找到发布按钮")
        return False

    def save_draft(self) -> bool:
        """存为草稿"""
        btn = self.device(text="存草稿")
        if btn.exists(timeout=3):
            btn.click()
            time.sleep(3)
            logger.info("📝 已存草稿")
            return True
        logger.error("未找到存草稿按钮")
        return False

    def publish_note(self, note: XhsNote, draft: bool = False) -> bool:
        """完整发布流程

        Args:
            note: 笔记内容
            draft: True=存草稿, False=直接发布
        """
        self.open_xhs()
        self.go_home()
        self.start_publish()
        self.select_latest_image(0)
        self.next_step()     # 相册预览 → 编辑
        self.next_step()     # 编辑 → 文案
        self.fill_note(note)

        if draft:
            return self.save_draft()
        return self.publish()


def push_image_to_phone(local_path: str, remote_dir: str = "/sdcard/Pictures/") -> str:
    """将本地图片推送到手机"""
    filename = Path(local_path).name
    remote_path = f"{remote_dir}{filename}"
    subprocess.run(
        ["adb", "push", local_path, remote_path],
        capture_output=True, check=True,
    )
    # 通知媒体扫描器
    subprocess.run(
        ["adb", "shell", "am", "broadcast",
         "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
         "-d", f"file://{remote_path}"],
        capture_output=True,
    )
    time.sleep(2)
    logger.info(f"已推送: {local_path} → {remote_path}")
    return remote_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    note = XhsNote(
        title="深圳这家日料我能吃一辈子！花椒刺身绝了",
        body="""进门就被那股子清新的wasabi香气拿捏了，老板是个在日本修行8年的狠人 🔪

点了招牌三文鱼刺身拼盘：
第一筷子：这鱼是活的吧！！
第二筷子：入口即化，脂香在嘴里炸开 💥
第三筷子：搭配花椒酱油，灵魂都在颤抖

🔥 必点清单：
• 三文鱼腩刺身（不点等于白来）
• 花椒酱油拌饭（隐藏菜单）
• 味噌汤（现熬8小时）

📍 南山区 | 💰 人均150 | ⏰ 建议17:00前到

ps：没收钱，纯路人安利！""",
        image_path="/sdcard/Pictures/1773102728333.png",
        hashtags=["深圳美食", "日料探店", "刺身控", "深圳必吃", "美食分享"],
    )

    pub = XhsPublisher()
    # 先存草稿，确认后再发布
    pub.publish_note(note, draft=True)
