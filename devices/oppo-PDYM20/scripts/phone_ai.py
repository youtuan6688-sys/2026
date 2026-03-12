"""
手机 AI App 自动化模块
通过 ADB + uiautomator2 操控手机上的 AI App 生成内容
零 API 费用，利用 DeepSeek / Gemini App 的免费额度
"""

import uiautomator2 as u2
import time
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = Path(__file__).parent.parent / "logs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AppConfig:
    package: str
    input_text: str           # 输入框的 text 属性
    input_class: str          # 输入框的 class
    send_desc: str            # 发送按钮的 content-desc
    new_chat_bounds: tuple    # 新对话按钮坐标 (x, y)
    wait_seconds: int         # 等待生成的秒数


DEEPSEEK = AppConfig(
    package="com.deepseek.chat",
    input_text="发消息或按住说话",
    input_class="android.widget.EditText",
    send_desc="发送",
    new_chat_bounds=(943, 171),   # 右上角 + 按钮
    wait_seconds=30,
)

GEMINI = AppConfig(
    package="com.google.android.apps.bard",
    input_text="",                # 需要实测后填入
    input_class="android.widget.EditText",
    send_desc="",
    new_chat_bounds=(0, 0),
    wait_seconds=30,
)


class PhoneAI:
    """通过 ADB 操控手机 AI App"""

    def __init__(self, serial: str | None = None):
        self.device = u2.connect(serial)
        info = self.device.info
        logger.info(f"连接设备: {info.get('productName', 'unknown')}")

    def screenshot(self, name: str) -> Path:
        path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
        self.device.screenshot(str(path))
        logger.info(f"截屏: {path}")
        return path

    def open_app(self, config: AppConfig) -> None:
        self.device.app_start(config.package)
        time.sleep(3)
        logger.info(f"打开 App: {config.package}")

    def new_chat(self, config: AppConfig) -> None:
        x, y = config.new_chat_bounds
        self.device.click(x, y)
        time.sleep(2)
        logger.info("新建对话")

    def send_prompt(self, config: AppConfig, prompt: str) -> None:
        """输入 prompt 并发送"""
        # 点击输入框
        input_box = self.device(text=config.input_text)
        if input_box.exists:
            input_box.click()
        else:
            self.device(className=config.input_class).click()
        time.sleep(1)

        # 输入中文
        self.device(className=config.input_class).set_text(prompt)
        time.sleep(0.5)

        # 点击发送
        send_btn = self.device(description=config.send_desc)
        if send_btn.exists:
            # 获取 bounds 中心点
            bounds = send_btn.info.get("bounds", {})
            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
            self.device.click(cx, cy)
        else:
            logger.warning("未找到发送按钮，尝试坐标点击")
            self.device.click(966, 1474)

        logger.info(f"已发送 prompt ({len(prompt)} 字)")

    def wait_for_reply(self, config: AppConfig) -> Path:
        """等待回复生成完毕，返回截屏路径"""
        logger.info(f"等待生成... ({config.wait_seconds}s)")
        time.sleep(config.wait_seconds)
        return self.screenshot("reply")

    def read_reply_text(self) -> str:
        """读取回复文本（通过 dump UI 树）"""
        xml = self.device.dump_hierarchy()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)

        texts = []
        for elem in root.iter("node"):
            cls = elem.get("class", "")
            text = elem.get("text", "")
            if text and "android.widget.TextView" in cls and len(text) > 20:
                texts.append(text)

        return "\n".join(texts)

    def generate_content(self, prompt: str, app: AppConfig = DEEPSEEK) -> str:
        """完整流程：打开 App → 新对话 → 输入 → 等待 → 读取回复"""
        self.open_app(app)
        self.new_chat(app)
        self.send_prompt(app, prompt)
        self.wait_for_reply(app)

        reply = self.read_reply_text()
        logger.info(f"获取回复: {len(reply)} 字")
        return reply


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    ai = PhoneAI()
    prompt = "请用小红书风格写一段关于咖啡探店的文案，要求：1.标题吸引人 2.正文200字 3.带emoji 4.语气像嘴贱但靠谱的年轻人"

    result = ai.generate_content(prompt)
    print("=" * 50)
    print(result)
