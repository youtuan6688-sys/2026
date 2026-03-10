"""Mixin: Feishu document handling for MessageRouter."""

import json
import logging

logger = logging.getLogger(__name__)


class DocsMixin:
    """Feishu document read/create/write/share commands."""

    def _handle_doc(self, text: str, sender_id: str):
        """Handle /doc commands: read, create, write, share."""
        parts = text.strip().split(None, 2)
        subcmd = parts[1] if len(parts) > 1 else "help"

        if subcmd == "list":
            folder_token = parts[2].strip() if len(parts) > 2 else ""
            files = self.doc_manager.list_folder(folder_token)
            if not files:
                self.sender.send_text(sender_id, "文件夹为空或无权访问")
                return
            type_icons = {"docx": "📄", "sheet": "📊", "bitable": "📋", "folder": "📁"}
            lines = [f"{type_icons.get(f['type'], '📎')} {f['name']} ({f['type']})" +
                     (f"\n   {f['url']}" if f['url'] else f"\n   token: {f['token']}")
                     for f in files]
            self._send_long_text(sender_id, f"云文档清单 ({len(files)} 个):\n\n" + "\n".join(lines))
            return

        if subcmd == "read" and len(parts) > 2:
            url_or_id = parts[2].strip()
            result = self.doc_manager.read_document(url_or_id)
            if result:
                content = result["content"][:3000] if result["content"] else "(空文档)"
                self._send_long_text(
                    sender_id,
                    f"文档: {result['title']}\nID: {result['doc_id']}\n\n{content}",
                )
            else:
                self.sender.send_text(sender_id, "读取文档失败，请检查链接或权限")
            return

        if subcmd == "create" and len(parts) > 2:
            title = parts[2].strip()
            result = self.doc_manager.create_document(title)
            if result:
                self.sender.send_text(
                    sender_id,
                    f"文档已创建:\n标题: {title}\nID: {result['doc_id']}\n链接: {result['url']}",
                )
            else:
                self.sender.send_text(sender_id, "创建文档失败")
            return

        if subcmd == "write" and len(parts) > 2:
            rest = parts[2].strip()
            write_parts = rest.split(None, 1)
            if len(write_parts) < 2:
                self.sender.send_text(sender_id, "用法: /doc write <文档ID或链接> <内容>")
                return
            doc_ref, content = write_parts
            if self.doc_manager.write_content(doc_ref, content):
                self.sender.send_text(sender_id, f"已写入文档 {doc_ref}")
            else:
                self.sender.send_text(sender_id, "写入失败，请检查权限")
            return

        if subcmd == "share" and len(parts) > 2:
            rest = parts[2].strip()
            share_parts = rest.split(None, 1)
            if len(share_parts) < 2:
                self.sender.send_text(sender_id, "用法: /doc share <文档ID或链接> <用户ID或邮箱>")
                return
            doc_ref, member = share_parts
            member_type = "email" if "@" in member else "openid"
            if self.doc_manager.share_document(doc_ref, member, member_type=member_type):
                self.sender.send_text(sender_id, f"已分享文档给 {member}")
            else:
                self.sender.send_text(sender_id, "分享失败，请检查权限")
            return

        self.sender.send_text(
            sender_id,
            "飞书文档命令:\n"
            "/doc list [文件夹token] — 列出云文档清单\n"
            "/doc read <链接或ID> — 读取文档内容\n"
            "/doc create <标题> — 创建新文档\n"
            "/doc write <ID或链接> <内容> — 写入内容到文档\n"
            "/doc share <ID或链接> <邮箱或open_id> — 分享文档",
        )

    def _handle_doc_natural(self, text: str, sender_id: str):
        """Handle natural language document requests via haiku."""
        prompt = (
            "用户想操作飞书在线文档。根据消息判断操作，只输出一行 JSON：\n"
            '- 读取: {"action":"read","target":"文档链接或ID"}\n'
            '- 创建: {"action":"create","title":"文档标题","content":"可选内容"}\n'
            '- 写入: {"action":"write","target":"文档链接或ID","content":"要写的内容"}\n'
            '- 创建并写入: {"action":"create_write","title":"标题","content":"内容"}\n'
            '- 分享: {"action":"share","target":"文档链接或ID","member":"邮箱或open_id"}\n\n'
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            action = parsed.get("action", "")

            if action == "read":
                target = parsed.get("target", "")
                if not target:
                    self.sender.send_text(sender_id, "请提供文档链接或ID")
                    return
                doc = self.doc_manager.read_document(target)
                if doc:
                    content = doc["content"][:3000] if doc["content"] else "(空文档)"
                    self._send_long_text(
                        sender_id,
                        f"文档: {doc['title']}\n\n{content}",
                    )
                else:
                    self.sender.send_text(sender_id, "读取文档失败")

            elif action == "create":
                title = parsed.get("title", "未命名文档")
                content = parsed.get("content", "")
                if content:
                    doc = self.doc_manager.create_and_write(title, content)
                else:
                    doc = self.doc_manager.create_document(title)
                if doc:
                    self.sender.send_text(
                        sender_id,
                        f"文档已创建:\n标题: {title}\n链接: {doc['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建文档失败")

            elif action == "create_write":
                title = parsed.get("title", "未命名文档")
                content = parsed.get("content", "")
                doc = self.doc_manager.create_and_write(title, content)
                if doc:
                    self.sender.send_text(
                        sender_id,
                        f"文档已创建并写入:\n标题: {title}\n链接: {doc['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建文档失败")

            elif action == "write":
                target = parsed.get("target", "")
                content = parsed.get("content", "")
                if not target or not content:
                    self.sender.send_text(sender_id, "请提供文档ID和要写入的内容")
                    return
                if self.doc_manager.write_content(target, content):
                    self.sender.send_text(sender_id, f"已写入文档")
                else:
                    self.sender.send_text(sender_id, "写入失败")

            elif action == "share":
                target = parsed.get("target", "")
                member = parsed.get("member", "")
                if not target or not member:
                    self.sender.send_text(sender_id, "请提供文档ID和要分享的用户")
                    return
                member_type = "email" if "@" in member else "openid"
                if self.doc_manager.share_document(target, member, member_type=member_type):
                    self.sender.send_text(sender_id, f"已分享文档给 {member}")
                else:
                    self.sender.send_text(sender_id, "分享失败")
            else:
                self.sender.send_text(sender_id, "没理解你的文档操作，试试: /doc help")

        except Exception as e:
            logger.warning(f"Natural doc handling failed: {e}")
            self.sender.send_text(sender_id, f"文档操作解析失败，试试命令: /doc help")
