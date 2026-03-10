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

            content_text, _ = file_handler.parse_file(
                file_path, file_name,
                gemini_api_key=settings.gemini_api_key,
                user_prompt=user_prompt,
            )

            if category == "image":
                reply = f"📷 图片分析结果：\n\n{content_text}"
                self.sender.send_text(sender_id, reply)
            else:
                # 铁律放 system prompt（高权重）
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
                    self.sender.send_text(
                        sender_id,
                        f"📊 「{file_name}」分析结果：\n\n{analysis}",
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
