"""
Gemini Pro 图片生成 + 下载模块
通过 ADB + uiautomator2 操控手机 Gemini App
零 API 成本，每张约 60-90s

支持：单图/批量生成、重试机制、迭代编辑
"""

import uiautomator2 as u2
import time
import logging
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── UI 元素 ID ───────────────────────────────────────

GEMINI_PKG = "com.google.android.apps.bard"
GEMINI_INPUT_RID = "com.google.android.googlequicksearchbox:id/assistant_robin_input_collapsed_text_half_sheet"
GEMINI_SEND_RID = "com.google.android.googlequicksearchbox:id/assistant_robin_send_icon_button"
GEMINI_NEW_CHAT_RID = "com.google.android.googlequicksearchbox:id/assistant_robin_new_chat_button"
GEMINI_MODE_RID = "com.google.android.googlequicksearchbox:id/assistant_robin_chat_input_mode_btn"
GEMINI_IMAGE_DESC = "生成的图片 1"
GEMINI_DOWNLOAD_DESC = "下载图片"
GEMINI_BACK_DESC = "返回"

MAX_RETRIES = 2
IMAGE_TIMEOUT = 120  # 秒


@dataclass
class GenerationResult:
    """单次生成结果"""
    success: bool
    local_path: Path | None = None
    remote_path: str | None = None
    prompt: str = ""
    duration_s: float = 0
    retries: int = 0
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class GeminiImageGenerator:
    """通过 ADB 操控 Gemini Pro 生成图片"""

    def __init__(self, serial: str | None = None):
        self.device = u2.connect(serial)
        self.session_log: list[GenerationResult] = []
        info = self.device.info
        logger.info(f"连接设备: {info.get('productName', 'unknown')}")

    # ── 基础操作 ─────────────────────────────────────

    def open_gemini(self) -> None:
        self.device.app_start(GEMINI_PKG)
        time.sleep(3)
        logger.info("Gemini 已打开")

    def new_chat(self) -> None:
        # 如果卡在大图查看界面，先返回
        if self.device(description=GEMINI_BACK_DESC).exists(timeout=1):
            self.device.press("back")
            time.sleep(1)

        btn = self.device(resourceId=GEMINI_NEW_CHAT_RID)
        if btn.exists(timeout=3):
            btn.click()
            time.sleep(2)
            logger.info("新建对话")

        self._ensure_pro_mode()

    def _ensure_pro_mode(self) -> None:
        """确保 Gemini 处于 Pro 模式（生图需要 Pro）"""
        mode_btn = self.device(resourceId=GEMINI_MODE_RID)
        if mode_btn.exists(timeout=2):
            current_text = mode_btn.info.get("text", "")
            if current_text != "Pro":
                mode_btn.click()
                time.sleep(1)
                pro_option = self.device(text="Pro")
                if pro_option.exists(timeout=2):
                    pro_option.click()
                    time.sleep(1)
                    logger.info("已切换到 Pro 模式")
            else:
                logger.info("已在 Pro 模式")

    def send_prompt(self, prompt: str) -> None:
        """输入 prompt 并发送"""
        input_box = self.device(resourceId=GEMINI_INPUT_RID)
        if input_box.exists(timeout=3):
            input_box.click()
        else:
            fallback = self.device(text="问问 Gemini")
            if fallback.exists(timeout=2):
                fallback.click()
            else:
                raise RuntimeError("找不到输入框")
        time.sleep(1)

        self.device(className="android.widget.EditText").set_text(prompt)
        time.sleep(0.5)

        send_btn = self.device(description="发送")
        if not send_btn.exists(timeout=3):
            raise RuntimeError("找不到发送按钮")
        send_btn.click()
        logger.info(f"已发送 prompt ({len(prompt)} 字)")

    def wait_for_image(self, timeout: int = IMAGE_TIMEOUT) -> bool:
        """等待图片生成完毕"""
        logger.info(f"等待图片生成 (最长 {timeout}s)...")
        start = time.time()
        while time.time() - start < timeout:
            # 检查是否生成了图片
            if self.device(description=GEMINI_IMAGE_DESC).exists:
                elapsed = int(time.time() - start)
                logger.info(f"图片生成完毕 ({elapsed}s)")
                return True
            # 检查是否出错（如内容政策拦截）
            if self.device(textContains="无法生成").exists:
                logger.warning("Gemini 拒绝生成（内容政策）")
                return False
            if self.device(textContains="出了点问题").exists:
                logger.warning("Gemini 报错")
                return False
            time.sleep(5)
        logger.warning("等待超时，图片可能未生成")
        return False

    def download_image(self) -> str | None:
        """点击图片 → 下载 → 返回，返回手机上的文件路径"""
        before = self._list_pictures()

        # 点击图片打开大图
        self.device(description=GEMINI_IMAGE_DESC).click()
        time.sleep(2)

        # 点击下载
        dl_btn = self.device(description=GEMINI_DOWNLOAD_DESC)
        if dl_btn.exists(timeout=5):
            dl_btn.click()
            logger.info("点击下载")
            time.sleep(8)
        else:
            logger.error("未找到下载按钮")
            self._safe_back()
            return None

        self._safe_back()

        # 找到新下载的文件
        after = self._list_pictures()
        new_files = [f for f in after if f not in before]

        if new_files:
            file_path = new_files[0]
            logger.info(f"图片已保存: {file_path}")
            return file_path

        logger.warning("未找到新下载的文件")
        return None

    def pull_to_local(self, remote_path: str, local_name: str) -> Path:
        """从手机拉取图片到本地 assets 目录"""
        local_path = ASSETS_DIR / local_name
        subprocess.run(
            ["adb", "pull", remote_path, str(local_path)],
            capture_output=True, check=True,
        )
        size_kb = local_path.stat().st_size / 1024
        logger.info(f"已拉取到: {local_path} ({size_kb:.0f}KB)")
        return local_path

    # ── 编辑能力（用嘴改图）──────────────────────────

    def edit_image(self, instruction: str, timeout: int = IMAGE_TIMEOUT) -> bool:
        """在当前对话中发送编辑指令（不新建对话）

        前提：当前对话中已有生成的图片。
        """
        logger.info(f"编辑指令: {instruction[:50]}...")
        self.send_prompt(instruction)
        return self.wait_for_image(timeout=timeout)

    # ── 高级流程 ─────────────────────────────────────

    def generate_and_download(
        self,
        prompt: str,
        filename: str,
        retries: int = MAX_RETRIES,
    ) -> GenerationResult:
        """完整流程：新对话 → 输入 prompt → 等待 → 下载 → 拉到本地

        带重试机制，失败时自动重新开始。
        """
        start = time.time()

        for attempt in range(retries + 1):
            try:
                self.open_gemini()
                self.new_chat()
                self.send_prompt(prompt)

                if not self.wait_for_image():
                    if attempt < retries:
                        logger.info(f"第 {attempt + 1} 次失败，重试...")
                        time.sleep(3)
                        continue
                    return self._make_result(
                        False, prompt, start, attempt, "图片生成失败/超时"
                    )

                remote_path = self.download_image()
                if not remote_path:
                    if attempt < retries:
                        logger.info(f"下载失败，重试...")
                        continue
                    return self._make_result(
                        False, prompt, start, attempt, "下载失败"
                    )

                local_path = self.pull_to_local(remote_path, filename)
                result = self._make_result(
                    True, prompt, start, attempt,
                    local_path=local_path, remote_path=remote_path,
                )
                self.session_log.append(result)
                return result

            except Exception as e:
                logger.error(f"异常: {e}")
                if attempt < retries:
                    logger.info(f"异常后重试...")
                    time.sleep(3)
                    continue
                result = self._make_result(
                    False, prompt, start, attempt, str(e)
                )
                self.session_log.append(result)
                return result

        # 不应到达这里
        return self._make_result(False, prompt, start, retries, "未知错误")

    def batch_generate(
        self,
        tasks: list[dict],
        delay_between: int = 5,
    ) -> list[GenerationResult]:
        """批量生成图片

        Args:
            tasks: [{"prompt": str, "filename": str}, ...]
            delay_between: 每张之间的间隔秒数
        """
        results = []
        total = len(tasks)
        logger.info(f"批量生成开始: {total} 张")

        for i, task in enumerate(tasks):
            logger.info(f"[{i + 1}/{total}] {task['filename']}")
            result = self.generate_and_download(
                prompt=task["prompt"],
                filename=task["filename"],
            )
            results.append(result)

            if i < total - 1:
                time.sleep(delay_between)

        success = sum(1 for r in results if r.success)
        logger.info(f"批量完成: {success}/{total} 成功")
        self._save_session_log()
        return results

    # ── 内部工具 ─────────────────────────────────────

    def _safe_back(self) -> None:
        """安全返回"""
        back_btn = self.device(description=GEMINI_BACK_DESC)
        if back_btn.exists(timeout=3):
            back_btn.click()
        else:
            self.device.press("back")
        time.sleep(1)

    def _list_pictures(self) -> list[str]:
        """列出手机 Pictures 目录的 png/jpg 文件"""
        result = subprocess.run(
            ["adb", "shell", "find", "/sdcard/Pictures/", "-maxdepth", "1",
             "-name", "*.png", "-o", "-name", "*.jpg"],
            capture_output=True, text=True,
        )
        return sorted(result.stdout.strip().split("\n")) if result.stdout.strip() else []

    def _make_result(
        self, success, prompt, start, retries, error="",
        local_path=None, remote_path=None,
    ) -> GenerationResult:
        return GenerationResult(
            success=success,
            local_path=local_path,
            remote_path=remote_path,
            prompt=prompt[:200],
            duration_s=round(time.time() - start, 1),
            retries=retries,
            error=error,
        )

    def _save_session_log(self) -> None:
        """保存本次会话的生成日志"""
        log_file = LOG_DIR / f"gemini_batch_{datetime.now():%Y%m%d_%H%M%S}.json"
        data = []
        for r in self.session_log:
            data.append({
                "success": r.success,
                "local_path": str(r.local_path) if r.local_path else None,
                "prompt": r.prompt,
                "duration_s": r.duration_s,
                "retries": r.retries,
                "error": r.error,
                "timestamp": r.timestamp,
            })
        log_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        logger.info(f"日志已保存: {log_file}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "config"))
    from image_style import build_from_template, build_prompt, SCENE_TEMPLATES

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    gen = GeminiImageGenerator()

    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        # 批量模式：python gemini_image.py batch
        tasks = []
        for name in ["咖啡探店", "吉卜力风景", "赛博朋克街景"]:
            tasks.append({
                "prompt": build_from_template(name, title=f"测试-{name}"),
                "filename": f"batch_{name}.png",
            })
        gen.batch_generate(tasks)
    else:
        # 单图模式
        template_name = sys.argv[1] if len(sys.argv) > 1 else "咖啡探店"
        if template_name in SCENE_TEMPLATES:
            prompt = build_from_template(template_name)
        else:
            prompt = build_prompt(subject=template_name)

        result = gen.generate_and_download(prompt, "test_output.png")
        if result.success:
            print(f"成功: {result.local_path} ({result.duration_s}s)")
        else:
            print(f"失败: {result.error}")
