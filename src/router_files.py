"""Mixin: File analysis, quoted messages, and stock queries for MessageRouter."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from src import file_handler
from src import stock_query
from src import chart_generator
from config.settings import settings

logger = logging.getLogger(__name__)

# File-level dedup: prevent same file from being processed multiple times
# Key: (file_key, prompt_hash) → timestamp
_FILE_DEDUP: dict[tuple, float] = {}
_FILE_DEDUP_TTL = 300  # 5 minutes


def _file_is_duplicate(file_key: str, user_prompt: str) -> bool:
    """Check if this file+prompt combo was recently processed."""
    now = time.time()

    # Clean old entries
    stale = [k for k, ts in _FILE_DEDUP.items() if now - ts > _FILE_DEDUP_TTL]
    for k in stale:
        del _FILE_DEDUP[k]

    key = (file_key, hash(user_prompt))
    if key in _FILE_DEDUP:
        logger.info(f"File dedup hit: file_key={file_key[-10:]}, skipping")
        return True

    _FILE_DEDUP[key] = now
    return False


class FilesMixin:
    """File message handling, quoted file analysis, and stock queries."""

    _FILE_LOG = Path("/Users/tuanyou/Happycode2026/data/file_requests.json")

    def _handle_file_message(self, sender_id: str, marker: str,
                              chat_type: str, sender_open_id: str):
        """Handle file messages: analyze supported types, log unsupported ones."""
        parts = marker.strip("[]").split(":", 4)
        msg_type = parts[1] if len(parts) > 1 else "unknown"
        file_name = parts[2] if len(parts) > 2 else ""
        file_key = parts[3] if len(parts) > 3 else ""
        message_id = parts[4] if len(parts) > 4 else ""

        user_id = sender_open_id or sender_id

        # image 类型：飞书图片的 file_name 是 image_key（无扩展名），强制当 .png 处理
        if msg_type == "image":
            if not file_name or not Path(file_name).suffix:
                file_name = f"{file_name or file_key}.png"

        self._log_file_request(user_id, sender_id, chat_type, msg_type, file_name, file_key)

        # 语音消息：飞书 ASR 转文字 → 当普通文本交给 Claude
        if msg_type == "audio":
            self._handle_audio_message(
                sender_id, file_key, message_id, chat_type, sender_open_id,
            )
            return

        # 合并转发消息：展开子消息，提取文本+图片一起分析
        if msg_type == "merge_forward":
            self._handle_merge_forward(
                sender_id, message_id, chat_type, sender_open_id,
            )
            return

        # image 类型来自飞书，一定是可处理的图片
        is_image_type = msg_type == "image"
        if is_image_type or (file_name and file_handler.is_supported(file_name)):
            # Check if user has an auto-act pattern for this file type
            auto_prompt = self._check_auto_pattern(user_id, file_name) if not is_image_type else ""

            # Log workflow match (engine ready for future step execution)
            if not is_image_type:
                try:
                    wf = self.workflow_engine.match_file(file_name, auto_prompt)
                    if wf:
                        logger.info(
                            f"Workflow matched: {wf['name']} for {file_name}"
                        )
                except Exception:
                    pass

            self._analyze_file(sender_id, msg_type, file_name, file_key,
                               message_id, chat_type, user_prompt=auto_prompt if not is_image_type else "",
                               sender_open_id=sender_open_id)
        else:
            type_labels = {"file": "文件", "image": "图片", "audio": "语音", "video": "视频", "media": "媒体"}
            label = type_labels.get(msg_type, msg_type)
            name_hint = f"「{file_name}」" if file_name else ""
            self.sender.send_text(
                sender_id,
                f"收到你的{label}{name_hint}，但暂时不支持这个格式 🫠\n\n"
                f"目前支持：Excel (.xlsx/.xls)、CSV、PDF、图片 (png/jpg/gif)\n"
                f"已记录你的需求，后续会支持更多格式 ✅",
            )

    def _handle_audio_message(self, sender_id: str, file_key: str,
                               message_id: str, chat_type: str,
                               sender_open_id: str):
        """Handle voice messages: transcribe via Feishu ASR, then route to Claude."""
        if _file_is_duplicate(file_key, "audio"):
            return

        self.sender.send_text(sender_id, "收到语音，正在识别... 🎙️")

        feishu_client = self.doc_manager.client
        file_path = file_handler.download_file(
            feishu_client, message_id, file_key, "voice.opus", "file",
        )

        if not file_path:
            self.sender.send_text(sender_id, "语音下载失败，请稍后重试 😵")
            return

        try:
            text = file_handler.transcribe_audio(feishu_client, file_path)

            if text.startswith("语音识别失败") or text.startswith("语音识别出错"):
                self.sender.send_text(sender_id, text)
                return

            if text == "语音内容为空或无法识别":
                self.sender.send_text(sender_id, "没听清，能再说一遍吗？🫠")
                return

            # 把转写文本当普通消息处理
            logger.info(f"Audio transcribed: {text[:100]}")
            self.handle_message(
                sender_id=sender_id,
                text=f"[语音转文字] {text}",
                chat_type=chat_type,
                sender_open_id=sender_open_id,
            )
        finally:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _log_file_request(self, user_id: str, sender_id: str, chat_type: str,
                           msg_type: str, file_name: str, file_key: str):
        """Append file request to log for tracking."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "chat_type": chat_type,
            "sender_id": sender_id,
            "msg_type": msg_type,
            "file_name": file_name,
            "file_key": file_key,
        }
        try:
            log_file = self._FILE_LOG
            existing = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
            existing.append(record)
            if len(existing) > 500:
                existing = existing[-500:]
            log_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to log file request: {e}", exc_info=True)

    def _check_auto_pattern(self, user_id: str, file_name: str) -> str:
        """Check if user has an auto-act pattern for this file type.

        Returns auto-generated prompt string, or empty string.
        """
        try:
            from src.pattern_detector import should_auto_act, EXCEL_AUTO_ANALYZE
            ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
            if ext not in ("xlsx", "xls", "csv"):
                return ""

            patterns = self.contacts.get_patterns(user_id)
            match = should_auto_act(patterns, "excel_upload")
            if match:
                logger.info(
                    f"Auto-pattern triggered for {user_id}: "
                    f"{match['action']} (count={match.get('count', 0)})"
                )
                return "帮我分析这个文件"
        except Exception as e:
            logger.debug(f"Auto-pattern check failed: {e}")
        return ""

    def _analyze_file(self, sender_id: str, msg_type: str, file_name: str,
                       file_key: str, message_id: str, chat_type: str,
                       user_prompt: str = "", sender_open_id: str = ""):
        """Download, parse, and analyze a supported file."""
        # File-level dedup: skip if same file+prompt processed recently
        if _file_is_duplicate(file_key, user_prompt):
            return

        category = file_handler.get_file_category(file_name)

        feishu_client = self.doc_manager.client
        resource_type = "image" if msg_type == "image" else "file"
        file_path = file_handler.download_file(
            feishu_client, message_id, file_key, file_name, resource_type,
        )

        if not file_path:
            self.sender.send_text(sender_id, f"下载「{file_name}」失败，请稍后重试 😵")
            return

        try:
            # Check if user wants a file operation (split/filter/etc.)
            if user_prompt and category in ("excel", "csv"):
                if self._try_file_operation(sender_id, file_path, file_name,
                                            user_prompt, chat_type):
                    return  # File op handled, skip normal analysis

            self.sender.send_text(sender_id, f"收到「{file_name}」，正在分析... ⏳")

            # Resolve user name for @mention in group replies
            user_name = ""
            if sender_open_id and sender_id.startswith("oc_"):
                user_name = self.contacts.get_name(sender_open_id) if hasattr(self, 'contacts') else ""

            if category == "image":
                # Claude Code 的 Read 工具原生支持看图片，直接传文件路径
                img_prompt = (
                    f"请先用 Read 工具读取图片文件：{file_path}\n"
                    f"然后详细分析图片内容。"
                )
                if user_prompt:
                    img_prompt += f"\n用户要求：{user_prompt}"
                else:
                    img_prompt += (
                        "\n如果包含文字，提取全部文字内容。"
                        "如果包含数据/图表，提取关键数据。"
                        "如果是截图/照片，描述画面并分析。"
                    )

                analysis = self.quota.call_claude(
                    img_prompt, "sonnet", timeout=90,
                )
                if analysis:
                    self._send_long_text(
                        sender_id, f"📷 图片分析结果：\n\n{analysis}",
                        at_user_id=sender_open_id, at_user_name=user_name,
                    )
                else:
                    self.sender.send_text(
                        sender_id, f"分析图片时 AI 没有返回结果，请稍后重试 😵",
                    )
                return

            content_text, _ = file_handler.parse_file(
                file_path, file_name,
                gemini_api_key=settings.gemini_api_key,
                user_prompt=user_prompt,
            )

            # 非图片文件：Excel/CSV/PDF 走文本解析 + Claude 分析
            sys_rules = (
                "你是数据分析助手。严格规则：\n"
                "1. 严禁编造数据！所有数字、百分比、排名必须直接来自下方文件内容。"
                "没有的数据就说「文件中无此信息」，绝不编造、不推算、不举例。\n"
                "2. 严禁编造操作！你不能创建文件、导出Excel、打包zip、生成下载链接。"
                "不要说「已生成」「已导出」「已打包」「已拆分成文件」等暗示你执行了文件操作的话。"
                "你只能分析数据和回答问题。\n"
                "3. 不要承诺做不到的事（实时监控、自动提醒、定时推送等）。\n"
                "4. 先给结论，再给数据支撑。用 markdown 表格展示数据。\n"
                "5. 推测性结论标注「⚠️ 推测」。\n"
            )
            if chat_type == "group":
                sys_rules += (
                    "6. 群聊模式：直接给结果，不寒暄、不角色扮演、不emoji轰炸。"
                    "结论→数据→建议，500字以内。\n"
                )

            if user_prompt:
                prompt = (
                    f"文件「{file_name}」({category.upper()}) 内容：\n\n"
                    f"{content_text}\n\n"
                    f"用户要求：{user_prompt}"
                )
            else:
                prompt = (
                    f"文件「{file_name}」({category.upper()}) 内容：\n\n"
                    f"{content_text}\n\n"
                    f"请分析：1.数据概况 2.关键指标 3.趋势洞察 4.建议"
                )

            analysis = self.quota.call_claude(
                prompt, "sonnet", timeout=90,
                extra_args=["--append-system-prompt", sys_rules],
            )

            if analysis:
                self._send_long_text(
                    sender_id,
                    f"📊 「{file_name}」分析结果：\n\n{analysis}",
                    at_user_id=sender_open_id, at_user_name=user_name,
                )
            else:
                self.sender.send_text(
                    sender_id,
                    f"分析「{file_name}」时 AI 没有返回结果，请稍后重试 😵",
                )

            # 自动生成图表（仅 Excel/CSV）
            if category in ("excel", "csv"):
                self._generate_and_send_charts(
                    sender_id, file_path, file_name, category,
                )
        finally:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _try_file_operation(self, sender_id: str, file_path: Path,
                            file_name: str, user_prompt: str,
                            chat_type: str) -> bool:
        """Detect and execute file operations (split, etc.). Returns True if handled."""
        columns = file_handler.get_columns(file_path)
        if not columns:
            return False

        op = file_handler.detect_file_op(user_prompt, columns)
        if not op:
            return False

        if op["op"] == "split":
            column = op["column"]

            # If column not identified, ask haiku to pick
            if not column:
                col_list = ", ".join(columns[:30])
                haiku_prompt = (
                    f"用户要求：{user_prompt}\n"
                    f"文件列名：{col_list}\n\n"
                    "用户想按哪个列拆分文件？只输出列名，不要其他内容。"
                    "如果无法判断，输出「无法判断」。"
                )
                result = self.quota.call_claude(haiku_prompt, "haiku", timeout=15)
                result = (result or "").strip().strip("\"'")
                if result and result != "无法判断" and result in columns:
                    column = result

            if not column:
                self.sender.send_text(
                    sender_id,
                    f"想按哪个列拆分？可选列名：\n"
                    + "\n".join(f"• {c}" for c in columns[:20]),
                )
                return True

            self.sender.send_text(
                sender_id,
                f"正在按「{column}」拆分「{file_name}」... ⏳",
            )

            split_files = file_handler.split_by_column(file_path, column, file_name)
            if not split_files:
                self.sender.send_text(sender_id, f"拆分失败：列「{column}」不存在或文件为空")
                return True

            # Send each split file
            sent_count = 0
            for split_path in split_files:
                if self.sender.send_file(sender_id, str(split_path)):
                    sent_count += 1
                try:
                    split_path.unlink(missing_ok=True)
                except Exception:
                    pass

            # Clean up split directory
            if split_files:
                try:
                    split_files[0].parent.rmdir()
                except Exception:
                    pass

            self.sender.send_text(
                sender_id,
                f"✅ 按「{column}」拆分完成，共 {sent_count} 个文件",
            )
            return True

        return False

    def _generate_and_send_charts(self, sender_id: str, file_path: Path,
                                    file_name: str, category: str):
        """从 Excel/CSV 生成图表并发送到飞书"""
        try:
            import pandas as pd

            if category == "excel":
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)

            if df.empty or len(df.columns) < 2:
                return

            chart_paths = chart_generator.auto_chart(df, title=file_name)

            for chart_path in chart_paths[:3]:  # 最多发3张图
                success = self.sender.send_image(sender_id, str(chart_path))
                if not success:
                    logger.warning(f"图表发送失败: {chart_path}")
                # 清理临时图片
                try:
                    chart_path.unlink(missing_ok=True)
                except Exception:
                    pass

            if chart_paths:
                logger.info(f"已发送 {len(chart_paths)} 张图表 for {file_name}")

        except Exception as e:
            logger.warning(f"图表生成失败 ({file_name}): {e}", exc_info=True)
            # 图表失败不影响文本分析结果，静默跳过

    def _fetch_message(self, message_id: str) -> dict | None:
        """Fetch a message by ID from Feishu API."""
        from lark_oapi.api.im.v1 import GetMessageRequest

        request = (
            GetMessageRequest.builder()
            .message_id(message_id)
            .build()
        )
        try:
            resp = self.doc_manager.client.im.v1.message.get(request)
            if not resp.success():
                logger.error(f"Failed to fetch message {message_id}: code={resp.code}, msg={resp.msg}")
                return None

            items = resp.data.items
            if not items:
                return None

            msg = items[0]
            body_content = msg.body.content if msg.body else None
            parsed_content = {}
            if body_content and body_content.strip():
                try:
                    parsed_content = json.loads(body_content)
                except json.JSONDecodeError:
                    logger.warning(f"Cannot parse body content for {message_id}: {body_content[:100]}")
            return {
                "message_id": msg.message_id,
                "msg_type": msg.msg_type,
                "content": parsed_content,
            }
        except Exception as e:
            logger.error(f"Error fetching message {message_id}: {e}", exc_info=True)
            return None

    def _handle_merge_forward(self, sender_id: str, message_id: str,
                               chat_type: str, sender_open_id: str,
                               user_prompt: str = ""):
        """Handle merge_forward messages: list sub-messages, extract text + images."""
        from lark_oapi.api.im.v1 import ListMessageRequest

        self.sender.send_text(sender_id, "正在打开转发记录... ⏳")

        # 用 merge_forward 作为 container_id_type 列出子消息
        request = (
            ListMessageRequest.builder()
            .container_id_type("merge_forward")
            .container_id(message_id)
            .page_size(50)
            .build()
        )
        try:
            resp = self.doc_manager.client.im.v1.message.list(request)
            if not resp.success():
                logger.error(f"Failed to list merge_forward sub-msgs: code={resp.code}, msg={resp.msg}")
                self.sender.send_text(
                    sender_id,
                    "打开转发记录失败，可能没有权限读取这些消息 🫠",
                )
                return
        except Exception as e:
            logger.error(f"Error listing merge_forward: {e}", exc_info=True)
            self.sender.send_text(sender_id, f"读取转发记录出错: {e}")
            return

        items = resp.data.items or []
        if not items:
            self.sender.send_text(sender_id, "转发记录是空的 🤷")
            return

        # 提取文本和图片
        texts = []
        image_infos = []  # (image_key, sub_message_id)
        feishu_client = self.doc_manager.client

        for msg in items:
            try:
                body_content = msg.body.content if msg.body and msg.body.content else None
                if not body_content:
                    continue
                content = json.loads(body_content)
            except (json.JSONDecodeError, AttributeError):
                continue

            if msg.msg_type == "text":
                texts.append(content.get("text", ""))
            elif msg.msg_type == "post":
                # 富文本：提取所有文字
                post_content = content.get("content", content)
                if isinstance(post_content, dict):
                    for lang_content in post_content.values():
                        if isinstance(lang_content, dict):
                            for para in lang_content.get("content", []):
                                for el in para:
                                    if el.get("tag") == "text":
                                        texts.append(el.get("text", ""))
                elif isinstance(post_content, list):
                    for para in post_content:
                        for el in para:
                            if el.get("tag") == "text":
                                texts.append(el.get("text", ""))
            elif msg.msg_type == "image":
                image_key = content.get("image_key", "")
                if image_key and len(image_infos) < 9:
                    image_infos.append((image_key, msg.message_id or ""))

        logger.info(
            f"Merge_forward parsed: {len(texts)} texts, {len(image_infos)} images "
            f"from {len(items)} sub-messages"
        )

        # 下载图片
        downloaded_paths = []
        for img_key, sub_mid in image_infos:
            file_name = f"{img_key}.png"
            file_path = file_handler.download_file(
                feishu_client, sub_mid, img_key, file_name, "image",
            )
            if file_path:
                downloaded_paths.append(str(file_path))

        # 组装 prompt
        combined_text = "\n".join(t for t in texts if t.strip())
        prompt_parts = []
        if combined_text:
            prompt_parts.append(f"转发记录中的文字内容：\n{combined_text[:5000]}")
        if downloaded_paths:
            read_cmds = "\n".join(
                f"- 图片{i+1}: {p}" for i, p in enumerate(downloaded_paths)
            )
            prompt_parts.append(
                f"请用 Read 工具读取以下 {len(downloaded_paths)} 张图片：\n{read_cmds}"
            )
        if user_prompt:
            prompt_parts.append(f"用户要求：{user_prompt}")
        else:
            prompt_parts.append(
                "请综合分析以上转发记录的内容。"
                "如果有图片，描述图片内容并与文字结合分析。"
                "如果有数据，提取关键信息。给出有价值的总结。"
            )

        full_prompt = "\n\n".join(prompt_parts)

        user_name = ""
        if sender_open_id and sender_id.startswith("oc_"):
            user_name = self.contacts.get_name(sender_open_id) if hasattr(self, 'contacts') else ""

        analysis = self.quota.call_claude(full_prompt, "sonnet", timeout=180)
        if analysis:
            label = f"📋 转发记录分析（{len(texts)}条文字"
            if downloaded_paths:
                label += f" + {len(downloaded_paths)}张图片"
            label += "）"
            self._send_long_text(
                sender_id, f"{label}：\n\n{analysis}",
                at_user_id=sender_open_id, at_user_name=user_name,
            )
        else:
            self.sender.send_text(sender_id, "分析转发记录时 AI 没有返回结果 😵")

        # Cleanup downloaded images
        for p in downloaded_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    def _fetch_recent_chat_images(self, chat_id: str, max_images: int = 9) -> list[dict]:
        """Fetch recent image messages from a group chat.

        Returns list of dicts: [{"image_key": ..., "message_id": ...}, ...]
        """
        from lark_oapi.api.im.v1 import ListMessageRequest

        request = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .page_size(30)
            .build()
        )
        try:
            resp = self.doc_manager.client.im.v1.message.list(request)
            if not resp.success():
                logger.error(f"Failed to list messages for {chat_id}: code={resp.code}, msg={resp.msg}")
                return []

            images = []
            for msg in (resp.data.items or []):
                if msg.msg_type != "image":
                    continue
                try:
                    content = json.loads(msg.body.content) if msg.body and msg.body.content else {}
                except (json.JSONDecodeError, AttributeError):
                    continue
                image_key = content.get("image_key", "")
                if image_key:
                    images.append({
                        "image_key": image_key,
                        "message_id": msg.message_id or "",
                    })
                if len(images) >= max_images:
                    break
            return images

        except Exception as e:
            logger.error(f"Error fetching recent images: {e}", exc_info=True)
            return []

    def handle_batch_images(self, sender_id: str, user_prompt: str,
                            sender_open_id: str = "", max_images: int = 9):
        """Fetch and analyze recent images from a group chat in batch."""
        images = self._fetch_recent_chat_images(sender_id, max_images=max_images)
        if not images:
            self.sender.send_text(sender_id, "最近没找到图片消息 🤷")
            return

        self.sender.send_text(
            sender_id,
            f"找到 {len(images)} 张图片，正在批量分析... ⏳",
        )

        feishu_client = self.doc_manager.client
        downloaded_paths = []
        for img in images:
            file_name = f"{img['image_key']}.png"
            file_path = file_handler.download_file(
                feishu_client, img["message_id"], img["image_key"],
                file_name, "image",
            )
            if file_path:
                downloaded_paths.append(str(file_path))

        if not downloaded_paths:
            self.sender.send_text(sender_id, "图片下载失败，请稍后重试 😵")
            return

        # Build prompt with all image paths for Claude to read
        read_cmds = "\n".join(
            f"- 图片{i+1}: {p}" for i, p in enumerate(downloaded_paths)
        )
        prompt = (
            f"请用 Read 工具依次读取以下 {len(downloaded_paths)} 张图片，"
            f"然后综合分析所有图片内容：\n{read_cmds}\n\n"
        )
        if user_prompt:
            prompt += f"用户要求：{user_prompt}\n"
        else:
            prompt += (
                "请分析这些图片的内容，如果有共同主题就总结。"
                "如果包含文字，提取关键文字。"
                "如果是产品/案例图，分析并对比。"
            )

        user_name = ""
        if sender_open_id and sender_id.startswith("oc_"):
            user_name = self.contacts.get_name(sender_open_id) if hasattr(self, 'contacts') else ""

        analysis = self.quota.call_claude(prompt, "sonnet", timeout=180)
        if analysis:
            self._send_long_text(
                sender_id,
                f"📷 批量图片分析（{len(downloaded_paths)} 张）：\n\n{analysis}",
                at_user_id=sender_open_id, at_user_name=user_name,
            )
        else:
            self.sender.send_text(sender_id, "图片分析 AI 没有返回结果，请稍后重试 😵")

        # Cleanup
        for p in downloaded_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    def _extract_quoted_text(self, parent_id: str) -> str:
        """Extract text content from a quoted message. Returns empty string if not text."""
        parent = self._fetch_message(parent_id)
        if not parent:
            return ""

        msg_type = parent.get("msg_type", "")
        content = parent.get("content", {})

        if msg_type == "text":
            return content.get("text", "")

        if msg_type == "post":
            # Rich text: extract all text elements
            texts = []
            post_content = content.get("content", content)
            if isinstance(post_content, dict):
                for lang_content in post_content.values():
                    if isinstance(lang_content, dict):
                        for paragraph in lang_content.get("content", []):
                            for element in paragraph:
                                if element.get("tag") == "text":
                                    texts.append(element.get("text", ""))
            elif isinstance(post_content, list):
                for paragraph in post_content:
                    for element in paragraph:
                        if element.get("tag") == "text":
                            texts.append(element.get("text", ""))
            return " ".join(texts)

        if msg_type == "interactive":
            return self._extract_card_text(content)

        return ""

    @staticmethod
    def _extract_card_text(card: dict) -> str:
        """Extract readable text from an interactive card message."""
        parts = []

        # Header title
        header = card.get("header", {})
        title = header.get("title", {})
        if isinstance(title, dict):
            parts.append(title.get("content", ""))
        elif isinstance(title, str):
            parts.append(title)

        # Elements: markdown content, plain text, button URLs
        for elem in card.get("elements", []):
            if not isinstance(elem, dict):
                continue
            tag = elem.get("tag", "")
            if tag == "markdown":
                parts.append(elem.get("content", ""))
            elif tag == "div":
                # div may contain text or fields
                text_obj = elem.get("text", {})
                if isinstance(text_obj, dict):
                    parts.append(text_obj.get("content", ""))
                for field in elem.get("fields", []):
                    field_text = field.get("text", {})
                    if isinstance(field_text, dict):
                        parts.append(field_text.get("content", ""))
            elif tag == "action":
                for action in elem.get("actions", []):
                    url = action.get("url", "")
                    if url:
                        parts.append(f"链接: {url}")

        return "\n".join(p for p in parts if p)

    def _search_conversation_history(self, search_text: str,
                                     max_results: int = 3) -> str:
        """Search daily_buffer JSONL files for past conversations matching search_text.

        Used when user quotes an old message to recover surrounding context.
        """
        from pathlib import Path
        import json as _json
        from datetime import date, timedelta

        buffer_dir = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")
        if not buffer_dir.exists():
            return ""

        # Extract keywords from search text (first 5 meaningful words)
        words = [w for w in search_text.replace("\n", " ").split()
                 if len(w) > 1 and w not in ("的", "了", "是", "在", "我", "你", "他")][:5]
        if not words:
            return ""

        # Search recent 7 days of buffer files
        today = date.today()
        matches = []
        for days_ago in range(7):
            d = today - timedelta(days=days_ago)
            fpath = buffer_dir / f"{d.isoformat()}.jsonl"
            if not fpath.exists():
                continue
            try:
                entries = []
                for line in fpath.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    entries.append(_json.loads(line))

                for i, entry in enumerate(entries):
                    combined = (entry.get("user_msg", "") + " " +
                                entry.get("bot_reply", ""))
                    # Match if at least 2 keywords found
                    hits = sum(1 for w in words if w in combined)
                    if hits >= min(2, len(words)):
                        # Grab surrounding context (1 before, 1 after)
                        context_entries = entries[max(0, i-1):i+2]
                        matches.append((hits, d.isoformat(), context_entries))
                        if len(matches) >= max_results:
                            break
            except Exception as e:
                logger.warning(f"Error searching buffer {fpath}: {e}")
                continue
            if len(matches) >= max_results:
                break

        if not matches:
            return ""

        # Format results
        matches.sort(key=lambda x: -x[0])  # Best matches first
        parts = ["[历史对话回查]"]
        for _, date_str, entries in matches[:max_results]:
            for e in entries:
                ts = e.get("ts", "")[:16]
                user_msg = e.get("user_msg", "")[:200]
                bot_reply = e.get("bot_reply", "")[:300]
                parts.append(f"[{ts}] 用户: {user_msg}")
                if bot_reply:
                    parts.append(f"[{ts}] 助手: {bot_reply}")
            parts.append("---")

        return "\n".join(parts)

    def _handle_quoted_file(self, sender_id: str, user_text: str,
                             parent_id: str, chat_type: str,
                             sender_open_id: str) -> bool:
        """Check if quoted message is a file and analyze it. Returns True if handled."""
        parent = self._fetch_message(parent_id)
        if not parent:
            return False

        msg_type = parent.get("msg_type", "")
        content = parent.get("content", {})

        if msg_type not in ("file", "image", "media"):
            return False

        file_name = content.get("file_name", content.get("image_key", ""))
        file_key = content.get("file_key", content.get("image_key", ""))
        message_id = parent.get("message_id", parent_id)

        if not file_key:
            return False

        # image 类型：飞书图片的 file_name 是 image_key（无扩展名），强制当 .png 处理
        if msg_type == "image":
            if not file_name or not Path(file_name).suffix:
                file_name = f"{file_name or file_key}.png"

        logger.info(f"Quoted file detected: type={msg_type}, name={file_name}, key={file_key}")

        user_id = sender_open_id or sender_id
        self._log_file_request(user_id, sender_id, chat_type, msg_type, file_name, file_key)

        # image 类型来自飞书，一定是可处理的图片
        is_image_type = msg_type == "image"
        if is_image_type or (file_name and file_handler.is_supported(file_name)):
            self._analyze_file(
                sender_id, msg_type, file_name, file_key,
                message_id, chat_type, user_prompt=user_text,
                sender_open_id=sender_open_id,
            )
        else:
            type_labels = {"file": "文件", "image": "图片", "media": "媒体"}
            label = type_labels.get(msg_type, msg_type)
            name_hint = f"「{file_name}」" if file_name else ""
            self.sender.send_text(
                sender_id,
                f"收到你引用的{label}{name_hint}，但暂时不支持这个格式 🫠\n\n"
                f"目前支持：Excel (.xlsx/.xls)、CSV、PDF、图片 (png/jpg/gif)\n",
            )

        return True

    def _handle_stock_query(self, text: str, sender_id: str):
        """Handle /stock command for stock data queries."""
        parts = text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            self.sender.send_text(
                sender_id,
                "用法：/stock <代码或名称>\n"
                "例如：/stock 002384、/stock 东山精密、/stock 01810",
            )
            return

        query = parts[1].strip()
        self.sender.send_text(sender_id, f"查询 {query} 中... 📈")

        try:
            result = stock_query.query_stock(query)
            self.sender.send_text(sender_id, result)
        except Exception as e:
            logger.error(f"Stock query error: {e}", exc_info=True)
            self.sender.send_text(sender_id, f"查询出错了: {e}")
