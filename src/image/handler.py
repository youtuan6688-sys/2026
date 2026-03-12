"""Image handler — /image command for Feishu bot.

Generates images via Gemini on phone (zero API cost),
sends results back through Feishu.
"""

import importlib.util
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEVICE_DIR = Path(__file__).parent.parent.parent / "devices" / "oppo-PDYM20"
SCRIPTS_DIR = DEVICE_DIR / "scripts"
CONFIG_DIR = DEVICE_DIR / "config"

MAX_BATCH = 20


def _load_device_module(name: str, directory: Path):
    """Load a module from device directory without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot find {name}.py in {directory}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ImageHandler:
    """Handle /image commands via Gemini on phone."""

    def __init__(self, sender):
        self.sender = sender
        self._generator = None

    def _get_generator(self):
        """Lazy-init GeminiImageGenerator (requires phone connection)."""
        if self._generator is None:
            gemini_mod = _load_device_module("gemini_image", SCRIPTS_DIR)
            try:
                self._generator = gemini_mod.GeminiImageGenerator()
            except Exception as e:
                logger.error(f"Failed to connect to phone: {e}")
                raise
        return self._generator

    def _get_style_module(self):
        """Lazy-load image_style module from device config."""
        if not hasattr(self, "_style_mod"):
            self._style_mod = _load_device_module("image_style", CONFIG_DIR)
        return self._style_mod

    def handle_command(self, command: str, sender_id: str) -> None:
        """Handle /image commands.

        Usage:
            /image              — show help & template list
            /image <模板名>      — generate from template
            /image <自由描述>    — generate from custom description
            /image batch <模板1> <模板2> ...  — batch generate
            /image edit <指令>   — edit last generated image
        """
        parts = command.strip().split(maxsplit=2)

        if len(parts) < 2:
            self._send_help(sender_id)
            return

        sub = parts[1].strip()
        args = parts[2] if len(parts) > 2 else ""

        if sub in ("help", "帮助"):
            self._send_help(sender_id)
        elif sub in ("list", "模板", "场景"):
            self._list_templates(sender_id)
        elif sub == "batch":
            self._cmd_batch(args, sender_id)
        elif sub in ("edit", "改", "编辑"):
            self._cmd_edit(args, sender_id)
        else:
            # Treat everything after /image as the subject
            subject = command[len("/image"):].strip()
            self._cmd_generate(subject, sender_id)

    def _cmd_generate(self, subject: str, sender_id: str) -> None:
        """Generate a single image — template name or free description."""
        style = self._get_style_module()

        is_template = subject in style.SCENE_TEMPLATES
        if is_template:
            prompt = style.build_from_template(subject)
            self.sender.send_text(
                sender_id,
                f"正在用模板「{subject}」生成图片，手机出图约需 60-90s...",
            )
        else:
            prompt = style.build_prompt(subject=subject)
            self.sender.send_text(
                sender_id,
                f"正在生成: {subject[:50]}...\n手机出图约需 60-90s",
            )

        thread = threading.Thread(
            target=self._generate_pipeline,
            args=(prompt, subject, sender_id),
            daemon=True,
        )
        thread.start()

    def _generate_pipeline(self, prompt: str, subject: str, sender_id: str) -> None:
        """Background pipeline: generate on phone → pull → send via Feishu."""
        try:
            gen = self._get_generator()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = subject[:20].replace("/", "_").replace(" ", "_")
            filename = f"feishu_{safe_name}_{ts}.png"

            result = gen.generate_and_download(prompt, filename)

            if result.success and result.local_path:
                local_path = str(result.local_path)
                sent = self.sender.send_image(sender_id, local_path)
                if sent:
                    self.sender.send_text(
                        sender_id,
                        f"出图完成 ({result.duration_s:.0f}s)\n"
                        f"场景: {subject}\n"
                        f"路径: {local_path}",
                    )
                else:
                    self.sender.send_text(
                        sender_id,
                        f"图片已生成但发送失败\n路径: {local_path}",
                    )
            else:
                self.sender.send_text(
                    sender_id,
                    f"生成失败: {result.error}\n"
                    f"耗时: {result.duration_s:.0f}s | 重试: {result.retries} 次",
                )

        except Exception as e:
            logger.exception(f"Image generation pipeline error: {e}")
            self.sender.send_text(sender_id, f"出图异常: {str(e)[:200]}")

    def _cmd_batch(self, args: str, sender_id: str) -> None:
        """Batch generate from template names, one per line or space-separated."""
        style = self._get_style_module()

        names = [n.strip() for n in args.replace("\n", " ").split() if n.strip()]
        if not names:
            self.sender.send_text(
                sender_id,
                "用法: /image batch 咖啡探店 吉卜力风景 赛博朋克街景",
            )
            return

        if len(names) > MAX_BATCH:
            self.sender.send_text(
                sender_id,
                f"最多批量生成 {MAX_BATCH} 张，你发了 {len(names)} 个模板",
            )
            return

        valid = [n for n in names if n in style.SCENE_TEMPLATES]
        invalid = [n for n in names if n not in style.SCENE_TEMPLATES]

        if invalid:
            self.sender.send_text(
                sender_id,
                f"未知模板: {', '.join(invalid)}\n发 /image list 查看可用模板",
            )
        if not valid:
            return

        self.sender.send_text(
            sender_id,
            f"批量生成 {len(valid)} 张图片，预计 {len(valid) * 90}s...\n"
            f"模板: {', '.join(valid)}",
        )

        thread = threading.Thread(
            target=self._batch_pipeline,
            args=(valid, sender_id),
            daemon=True,
        )
        thread.start()

    def _batch_pipeline(self, template_names: list[str], sender_id: str) -> None:
        """Background batch generation."""
        style = self._get_style_module()

        try:
            gen = self._get_generator()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            succeeded = []
            failed = []

            for i, name in enumerate(template_names, 1):
                self.sender.send_text(
                    sender_id, f"[{i}/{len(template_names)}] 生成: {name}",
                )
                prompt = style.build_from_template(name)
                filename = f"batch_{name}_{ts}_{i}.png"
                result = gen.generate_and_download(prompt, filename)

                if result.success and result.local_path:
                    self.sender.send_image(sender_id, str(result.local_path))
                    succeeded.append(name)
                else:
                    failed.append(f"{name}: {result.error}")

            summary = f"批量完成: {len(succeeded)}/{len(template_names)} 成功"
            if failed:
                summary += "\n失败:\n  " + "\n  ".join(failed)
            self.sender.send_text(sender_id, summary)

        except Exception as e:
            logger.exception(f"Batch image error: {e}")
            self.sender.send_text(sender_id, f"批量出图异常: {str(e)[:200]}")

    def _cmd_edit(self, instruction: str, sender_id: str) -> None:
        """Edit the last generated image with natural language instruction."""
        if not instruction:
            self.sender.send_text(
                sender_id,
                "用法: /image edit <修改指令>\n"
                "例如: /image edit 把背景改成蓝色",
            )
            return

        self.sender.send_text(sender_id, f"正在编辑: {instruction[:50]}...")

        thread = threading.Thread(
            target=self._edit_pipeline,
            args=(instruction, sender_id),
            daemon=True,
        )
        thread.start()

    def _edit_pipeline(self, instruction: str, sender_id: str) -> None:
        """Background edit pipeline."""
        try:
            gen = self._get_generator()
            success = gen.edit_image(instruction)

            if success:
                remote_path = gen.download_image()
                if remote_path:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    local_path = gen.pull_to_local(
                        remote_path, f"edit_{ts}.png",
                    )
                    self.sender.send_image(sender_id, str(local_path))
                    self.sender.send_text(sender_id, "编辑完成!")
                else:
                    self.sender.send_text(sender_id, "编辑成功但下载失败")
            else:
                self.sender.send_text(sender_id, "编辑失败，Gemini 未返回新图片")

        except Exception as e:
            logger.exception(f"Image edit error: {e}")
            self.sender.send_text(sender_id, f"编辑异常: {str(e)[:200]}")

    def _list_templates(self, sender_id: str) -> None:
        """List available scene templates, auto-detecting categories from module."""
        style = self._get_style_module()
        templates = style.SCENE_TEMPLATES

        # Use module's categories if available, otherwise list flat
        categories = getattr(style, "TEMPLATE_CATEGORIES", None)
        lines = ["可用场景模板:"]

        if categories:
            for cat, names in categories.items():
                available = [n for n in names if n in templates]
                if available:
                    lines.append(f"\n【{cat}】")
                    lines.extend(f"  {n}" for n in available)
            # Any uncategorized templates
            all_categorized = {n for names in categories.values() for n in names}
            extra = [n for n in templates if n not in all_categorized]
            if extra:
                lines.append("\n【其他】")
                lines.extend(f"  {n}" for n in extra)
        else:
            lines.extend(f"  {n}" for n in templates)

        lines.append(f"\n共 {len(templates)} 个模板")
        lines.append("用法: /image <模板名> 或 /image <自由描述>")
        self.sender.send_text(sender_id, "\n".join(lines))

    def _send_help(self, sender_id: str) -> None:
        self.sender.send_text(
            sender_id,
            "图片生成命令 (手机 Gemini Pro 零成本出图):\n\n"
            "  /image <场景名>     — 从模板生成 (如: /image 咖啡探店)\n"
            "  /image <自由描述>   — 自定义生成 (如: /image 一只橘猫在阳光下打盹)\n"
            "  /image batch <模板> — 批量生成多张\n"
            "  /image edit <指令>  — 编辑上一张图\n"
            "  /image list        — 查看所有模板\n\n"
            "每张约 60-90s，每天免费 100 张",
        )
