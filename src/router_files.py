"""Mixin: File analysis, quoted messages, and stock queries for MessageRouter."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src import file_handler
from src import stock_query
from config.settings import settings

logger = logging.getLogger(__name__)


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

        self._log_file_request(user_id, sender_id, chat_type, msg_type, file_name, file_key)

        if file_name and file_handler.is_supported(file_name):
            self._analyze_file(sender_id, msg_type, file_name, file_key, message_id, chat_type)
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

    def _analyze_file(self, sender_id: str, msg_type: str, file_name: str,
                       file_key: str, message_id: str, chat_type: str,
                       user_prompt: str = ""):
        """Download, parse, and analyze a supported file."""
        category = file_handler.get_file_category(file_name)

        self.sender.send_text(sender_id, f"收到「{file_name}」，正在分析... ⏳")

        feishu_client = self.doc_manager.client
        resource_type = "image" if msg_type == "image" else "file"
        file_path = file_handler.download_file(
            feishu_client, message_id, file_key, file_name, resource_type,
        )

        if not file_path:
            self.sender.send_text(sender_id, f"下载「{file_name}」失败，请稍后重试 😵")
            return

        try:
            content_text, _ = file_handler.parse_file(
                file_path, file_name,
                gemini_api_key=settings.gemini_api_key,
                user_prompt=user_prompt,
            )

            if category == "image":
                reply = f"📷 图片分析结果：\n\n{content_text}"
                self.sender.send_text(sender_id, reply)
            else:
                if user_prompt:
                    prompt = (
                        f"用户发送了一个{category.upper()}文件「{file_name}」，内容如下：\n\n"
                        f"{content_text}\n\n"
                        f"用户的要求：{user_prompt}\n\n"
                        f"请根据用户要求分析数据，回复简洁实用，用中文。"
                    )
                else:
                    prompt = (
                        f"用户发送了一个{category.upper()}文件「{file_name}」，内容如下：\n\n"
                        f"{content_text}\n\n"
                        f"请分析这个数据：\n"
                        f"1. 概述数据内容和结构\n"
                        f"2. 找出关键数据点和趋势\n"
                        f"3. 给出有价值的洞察\n"
                        f"回复要简洁实用，用中文。"
                    )

                analysis = self.quota.call_claude(prompt, "sonnet", timeout=90)

                if analysis:
                    self.sender.send_text(
                        sender_id,
                        f"📊 「{file_name}」分析结果：\n\n{analysis}",
                    )
                else:
                    self.sender.send_text(
                        sender_id,
                        f"分析「{file_name}」时 AI 没有返回结果，请稍后重试 😵",
                    )
        finally:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

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
            return {
                "message_id": msg.message_id,
                "msg_type": msg.msg_type,
                "content": json.loads(body_content) if body_content else {},
            }
        except Exception as e:
            logger.error(f"Error fetching message {message_id}: {e}", exc_info=True)
            return None

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

        logger.info(f"Quoted file detected: type={msg_type}, name={file_name}, key={file_key}")

        user_id = sender_open_id or sender_id
        self._log_file_request(user_id, sender_id, chat_type, msg_type, file_name, file_key)

        if file_name and file_handler.is_supported(file_name):
            self._analyze_file(
                sender_id, msg_type, file_name, file_key,
                message_id, chat_type, user_prompt=user_text,
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
