"""Mixin: Feishu document + bitable handling for MessageRouter."""

import json
import logging

logger = logging.getLogger(__name__)


class DocsMixin:
    """Feishu document and bitable commands."""

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
            "用户想操作飞书在线文档或多维表格。根据消息判断操作，只输出一行 JSON：\n"
            '- 询问能力/帮助: {"action":"inquiry"}\n'
            '- 列表: {"action":"list","folder":"文件夹token或空"}\n'
            "--- 文档操作 ---\n"
            '- 读取文档: {"action":"read","target":"文档链接或ID"}\n'
            '- 创建文档: {"action":"create","title":"文档标题","content":"可选内容"}\n'
            '- 写入文档: {"action":"write","target":"文档链接或ID","content":"要写的内容"}\n'
            '- 创建并写入: {"action":"create_write","title":"标题","content":"内容"}\n'
            '- 分享文档: {"action":"share","target":"文档链接或ID","member":"邮箱或open_id"}\n'
            "--- 多维表格操作 ---\n"
            '- 创建多维表格: {"action":"bt_create","name":"表格名称"}\n'
            '- 查看表格列表: {"action":"bt_tables","app_token":"多维表格链接或token"}\n'
            '- 读取记录: {"action":"bt_read","app_token":"token","table_id":"可选"}\n'
            '- 新增记录: {"action":"bt_add","app_token":"token","table_id":"tblXXX","fields":{"字段":"值"}}\n'
            '- 更新记录: {"action":"bt_update","app_token":"token","table_id":"tblXXX","record_id":"recXXX","fields":{"字段":"新值"}}\n'
            '- 删除记录: {"action":"bt_delete","app_token":"token","table_id":"tblXXX","record_id":"recXXX"}\n'
            "--- 电子表格操作 ---\n"
            '- 创建电子表格: {"action":"ss_create","title":"表格名称"}\n'
            '- 查看工作表: {"action":"ss_sheets","token":"电子表格链接或token"}\n'
            '- 读取单元格: {"action":"ss_read","token":"token","range":"Sheet1!A1:C10"}\n'
            '- 写入单元格: {"action":"ss_write","token":"token","range":"Sheet1!A1:C2","values":[["姓名","年龄"],["张三",28]]}\n'
            '- 追加行: {"action":"ss_append","token":"token","range":"Sheet1!A:C","values":[["新数据1","新数据2"]]}\n\n'
            "注意：如果用户只是在询问能力，选 inquiry。如果提到多维表格/bitable，用 bt_ 前缀；电子表格/spreadsheet/excel，用 ss_ 前缀。\n\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            action = parsed.get("action", "")

            if action == "inquiry":
                self.sender.send_text(
                    sender_id,
                    "可以的！我目前支持以下飞书云文档操作：\n\n"
                    "📄 文档 (docx)\n"
                    "• 创建文档 — 「帮我创建一个叫XX的文档」\n"
                    "• 读取文档 — 「读一下这个文档 <链接>」\n"
                    "• 写入内容 — 「往XX文档里写入...」\n"
                    "• 分享文档 — 「把这个文档分享给XX」\n\n"
                    "📋 多维表格 (bitable)\n"
                    "• 创建表格 — 「创建一个多维表格叫XX」\n"
                    "• 查看数据表 — 「看看这个多维表格有哪些表 <链接>」\n"
                    "• 读取记录 — 「读一下这个多维表格的数据 <链接>」\n"
                    "• 新增记录 — 「往多维表格里加一条：姓名=张三, 年龄=28」\n"
                    "• 更新/删除记录 — 需提供 record_id\n\n"
                    "📊 电子表格 (sheet)\n"
                    "• 创建表格 — 「创建一个电子表格叫XX」\n"
                    "• 查看工作表 — 「看看这个表格有哪些sheet <链接>」\n"
                    "• 读取数据 — 「读一下这个表格A1到C10 <链接>」\n"
                    "• 写入数据 — 「往表格A1写入...」\n"
                    "• 追加行 — 「往表格追加一行数据」\n\n"
                    "📁 文件夹\n"
                    "• 列出文件 — 「列一下云文档」或 /doc list\n\n"
                    "你可以直接用自然语言告诉我要做什么，也可以用命令 /doc help 查看完整用法。",
                )
                return

            if action == "list":
                folder = parsed.get("folder", "")
                files = self.doc_manager.list_folder(folder)
                if not files:
                    self.sender.send_text(sender_id, "文件夹为空或无权访问")
                    return
                type_icons = {"docx": "📄", "sheet": "📊", "bitable": "📋", "folder": "📁"}
                lines = [f"{type_icons.get(f['type'], '📎')} {f['name']} ({f['type']})" +
                         (f"\n   {f['url']}" if f['url'] else f"\n   token: {f['token']}")
                         for f in files]
                self._send_long_text(sender_id, f"云文档清单 ({len(files)} 个):\n\n" + "\n".join(lines))
                return

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
            # ── Bitable actions ──

            elif action == "bt_create":
                name = parsed.get("name", "未命名多维表格")
                result = self.bitable_manager.create_app(name)
                if result:
                    self.sender.send_text(
                        sender_id,
                        f"多维表格已创建:\n名称: {name}\n链接: {result['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建多维表格失败，请检查权限")

            elif action == "bt_tables":
                app_token = parsed.get("app_token", "")
                if not app_token:
                    self.sender.send_text(sender_id, "请提供多维表格链接或 app_token")
                    return
                tables = self.bitable_manager.list_tables(app_token)
                if tables:
                    lines = [f"📋 {t['name']} (ID: {t['table_id']})" for t in tables]
                    self._send_long_text(
                        sender_id,
                        f"多维表格包含 {len(tables)} 个数据表:\n\n" + "\n".join(lines),
                    )
                else:
                    self.sender.send_text(sender_id, "未找到数据表，请检查链接或权限")

            elif action == "bt_read":
                app_token = parsed.get("app_token", "")
                table_id = parsed.get("table_id", "")
                if not app_token:
                    self.sender.send_text(sender_id, "请提供多维表格链接或 app_token")
                    return
                # If no table_id, list tables first
                if not table_id:
                    tables = self.bitable_manager.list_tables(app_token)
                    if not tables:
                        self.sender.send_text(sender_id, "未找到数据表")
                        return
                    table_id = tables[0]["table_id"]
                    table_name = tables[0]["name"]
                else:
                    table_name = table_id

                result = self.bitable_manager.list_records(app_token, table_id)
                records = result.get("records", [])
                formatted = self.bitable_manager.format_records(records)
                has_more = result.get("has_more", False)
                more_text = "\n\n(还有更多记录，可指定 table_id 和翻页)" if has_more else ""
                self._send_long_text(
                    sender_id,
                    f"数据表「{table_name}」的记录:\n\n{formatted}{more_text}",
                )

            elif action == "bt_add":
                app_token = parsed.get("app_token", "")
                table_id = parsed.get("table_id", "")
                fields = parsed.get("fields", {})
                if not app_token or not table_id or not fields:
                    self.sender.send_text(
                        sender_id,
                        "新增记录需要: app_token, table_id, 和字段内容\n"
                        "例: 「往多维表格 bascnXXX 的表 tblXXX 加一条: 姓名=张三, 状态=进行中」",
                    )
                    return
                result = self.bitable_manager.create_record(app_token, table_id, fields)
                if result:
                    self.sender.send_text(
                        sender_id,
                        f"记录已创建 (ID: {result['record_id']})",
                    )
                else:
                    self.sender.send_text(sender_id, "创建记录失败，请检查字段名和权限")

            elif action == "bt_update":
                app_token = parsed.get("app_token", "")
                table_id = parsed.get("table_id", "")
                record_id = parsed.get("record_id", "")
                fields = parsed.get("fields", {})
                if not all([app_token, table_id, record_id, fields]):
                    self.sender.send_text(sender_id, "更新记录需要: app_token, table_id, record_id, 和要更新的字段")
                    return
                if self.bitable_manager.update_record(app_token, table_id, record_id, fields):
                    self.sender.send_text(sender_id, f"记录 {record_id} 已更新")
                else:
                    self.sender.send_text(sender_id, "更新失败")

            elif action == "bt_delete":
                app_token = parsed.get("app_token", "")
                table_id = parsed.get("table_id", "")
                record_id = parsed.get("record_id", "")
                if not all([app_token, table_id, record_id]):
                    self.sender.send_text(sender_id, "删除记录需要: app_token, table_id, record_id")
                    return
                if self.bitable_manager.delete_record(app_token, table_id, record_id):
                    self.sender.send_text(sender_id, f"记录 {record_id} 已删除")
                else:
                    self.sender.send_text(sender_id, "删除失败")

            # ── Spreadsheet actions ──

            elif action == "ss_create":
                title = parsed.get("title", "未命名电子表格")
                result = self.sheets_manager.create_spreadsheet(title)
                if result:
                    self.sender.send_text(
                        sender_id,
                        f"电子表格已创建:\n名称: {title}\n链接: {result['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建电子表格失败，请检查权限")

            elif action == "ss_sheets":
                token = parsed.get("token", "")
                if not token:
                    self.sender.send_text(sender_id, "请提供电子表格链接或 token")
                    return
                sheets = self.sheets_manager.list_sheets(token)
                if sheets:
                    lines = [
                        f"📊 {s['title']} (ID: {s['sheet_id']}, {s['row_count']}行×{s['col_count']}列)"
                        for s in sheets
                    ]
                    self._send_long_text(
                        sender_id,
                        f"电子表格包含 {len(sheets)} 个工作表:\n\n" + "\n".join(lines),
                    )
                else:
                    self.sender.send_text(sender_id, "未找到工作表，请检查链接或权限")

            elif action == "ss_read":
                token = parsed.get("token", "")
                range_str = parsed.get("range", "")
                if not token:
                    self.sender.send_text(sender_id, "请提供电子表格链接或 token")
                    return
                # If no range, auto-detect first sheet
                if not range_str:
                    sheets = self.sheets_manager.list_sheets(token)
                    if sheets:
                        range_str = f"{sheets[0]['sheet_id']}!A1:J20"
                    else:
                        self.sender.send_text(sender_id, "无法获取工作表信息")
                        return
                values = self.sheets_manager.read_range(token, range_str)
                if values is not None:
                    formatted = self.sheets_manager.format_cells(values)
                    self._send_long_text(sender_id, f"数据 ({range_str}):\n\n{formatted}")
                else:
                    self.sender.send_text(sender_id, "读取失败，请检查范围格式和权限")

            elif action == "ss_write":
                token = parsed.get("token", "")
                range_str = parsed.get("range", "")
                values = parsed.get("values", [])
                if not token or not range_str or not values:
                    self.sender.send_text(
                        sender_id,
                        "写入需要: token, range, values\n"
                        "例: 「往表格 shtcnXXX 的 Sheet1!A1 写入：姓名, 年龄」",
                    )
                    return
                if self.sheets_manager.write_range(token, range_str, values):
                    self.sender.send_text(sender_id, f"已写入 {len(values)} 行到 {range_str}")
                else:
                    self.sender.send_text(sender_id, "写入失败")

            elif action == "ss_append":
                token = parsed.get("token", "")
                range_str = parsed.get("range", "")
                values = parsed.get("values", [])
                if not token or not range_str or not values:
                    self.sender.send_text(
                        sender_id,
                        "追加需要: token, range (列范围), values\n"
                        "例: 「往表格 shtcnXXX 的 Sheet1!A:C 追加一行：张三, 28, 北京」",
                    )
                    return
                if self.sheets_manager.append_rows(token, range_str, values):
                    self.sender.send_text(sender_id, f"已追加 {len(values)} 行")
                else:
                    self.sender.send_text(sender_id, "追加失败")

            else:
                self.sender.send_text(sender_id, "没理解你的文档操作，试试: /doc help")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Natural doc parse failed: {e}")
            # Fallback: treat as inquiry
            self.sender.send_text(
                sender_id,
                "我支持飞书云文档操作（创建/读取/写入/分享），"
                "但没理解你具体要做什么。\n\n"
                "你可以这样说：\n"
                "• 「帮我创建一个叫XX的文档」\n"
                "• 「读一下这个文档 <链接>」\n"
                "• 「列一下云文档」\n\n"
                "或输入 /doc help 查看完整命令。",
            )
        except Exception as e:
            logger.error(f"Natural doc handling error: {e}")
            self.sender.send_text(sender_id, f"文档操作出错了: {e}")
