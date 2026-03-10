"""Mixin: Tmux/Loop/Session and Scheduled Task approval for MessageRouter."""

import json
import logging

from src import tmux_manager
from src import task_scheduler

logger = logging.getLogger(__name__)


class SessionsMixin:
    """Tmux session management and scheduled task approval flow."""

    # ── Tmux Session Management ──

    def _handle_loop(self, text: str, sender_id: str):
        """Handle /loop commands: start or stop a loop session."""
        parts = text.strip().split(None, 2)
        if len(parts) >= 2 and parts[1] == "stop":
            name = parts[2] if len(parts) > 2 else "loop"
            if tmux_manager.stop_session(name):
                self.sender.send_text(sender_id, f"已停止循环会话: {name}")
            else:
                self.sender.send_text(sender_id, f"停止会话失败: {name}")
            return

        if len(parts) < 2:
            self.sender.send_text(
                sender_id,
                "用法:\n/loop <间隔> [提示] — 启动定时任务 (如: /loop 60m 检查状态)\n/loop stop [名称] — 停止",
            )
            return

        interval = parts[1]
        name = f"loop-{interval}"

        if tmux_manager.start_loop_session(name=name, interval=interval):
            msg = f"已启动循环会话 {name}，间隔 {interval}"
            if len(parts) > 2:
                import time
                time.sleep(3)
                tmux_manager.send_keys(name, parts[2])
                msg += f"\n任务: {parts[2]}"
            self.sender.send_text(sender_id, msg)
        else:
            self.sender.send_text(sender_id, f"启动失败，可能已有同名会话: {name}")

    def _handle_session(self, text: str, sender_id: str):
        """Handle /session commands: list, stop, output."""
        parts = text.strip().split(None, 2)
        subcmd = parts[1] if len(parts) > 1 else "list"

        if subcmd == "list":
            status = tmux_manager.format_status()
            self.sender.send_text(sender_id, status)
            return

        if subcmd == "stop" and len(parts) > 2:
            name = parts[2]
            if tmux_manager.stop_session(name):
                self.sender.send_text(sender_id, f"已停止: {name}")
            else:
                self.sender.send_text(sender_id, f"停止失败: {name}")
            return

        if subcmd == "output" and len(parts) > 2:
            name = parts[2]
            output = tmux_manager.capture_output(name, lines=30)
            self._send_long_text(sender_id, f"会话 {name} 最近输出:\n\n{output}")
            return

        self.sender.send_text(
            sender_id,
            "用法:\n/session list — 查看会话\n/session stop <名称> — 停止\n/session output <名称> — 查看输出",
        )

    def _handle_loop_natural(self, text: str, sender_id: str):
        """Handle natural language loop requests via Claude."""
        sessions = tmux_manager.list_sessions()
        session_info = ", ".join(s.name for s in sessions) if sessions else "无"

        prompt = (
            "用户想管理定时循环任务。根据消息判断操作，只输出一行 JSON：\n"
            '- 启动: {"action":"start","interval":"60m","task":"任务描述"}\n'
            '- 停止: {"action":"stop","name":"会话名"}\n'
            '- 查看: {"action":"list"}\n\n'
            f"当前运行的会话: {session_info}\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            parsed = json.loads(raw.strip("`").strip())
            action = parsed.get("action", "list")

            if action == "start":
                interval = parsed.get("interval", "60m")
                task = parsed.get("task", "")
                name = f"loop-{interval}"
                if tmux_manager.start_loop_session(name=name, interval=interval):
                    msg = f"已启动循环任务，间隔 {interval}"
                    if task:
                        import time
                        time.sleep(3)
                        tmux_manager.send_keys(name, task)
                        msg += f"\n任务: {task}"
                    self.sender.send_text(sender_id, msg)
                else:
                    self.sender.send_text(sender_id, f"启动失败，可能已有同名会话: {name}")
            elif action == "stop":
                name = parsed.get("name", "loop-60m")
                if tmux_manager.stop_session(name):
                    self.sender.send_text(sender_id, f"已停止: {name}")
                else:
                    self.sender.send_text(sender_id, f"停止失败: {name}")
            else:
                status = tmux_manager.format_status()
                self.sender.send_text(sender_id, status)
        except Exception as e:
            logger.warning(f"Natural loop handling failed: {e}")
            self.sender.send_text(sender_id, f"没理解你的意思，试试: /loop 60m 任务描述")

    def _handle_session_natural(self, text: str, sender_id: str):
        """Handle natural language session management via Claude."""
        sessions = tmux_manager.list_sessions()
        session_info = ", ".join(f"{s.name}({'活跃' if s.alive else '停止'})" for s in sessions) if sessions else "无"

        prompt = (
            "用户想管理运行中的会话。根据消息判断操作，只输出一行 JSON：\n"
            '- 查看: {"action":"list"}\n'
            '- 停止: {"action":"stop","name":"会话名"}\n'
            '- 查看输出: {"action":"output","name":"会话名"}\n\n'
            f"当前会话: {session_info}\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            parsed = json.loads(raw.strip("`").strip())
            action = parsed.get("action", "list")

            if action == "stop":
                name = parsed.get("name", "")
                if name and tmux_manager.stop_session(name):
                    self.sender.send_text(sender_id, f"已停止: {name}")
                else:
                    self.sender.send_text(sender_id, f"停止失败: {name}")
            elif action == "output":
                name = parsed.get("name", "")
                if name:
                    output = tmux_manager.capture_output(name, lines=30)
                    self._send_long_text(sender_id, f"会话 {name} 最近输出:\n\n{output}")
                else:
                    self.sender.send_text(sender_id, "请指定会话名称")
            else:
                status = tmux_manager.format_status()
                self.sender.send_text(sender_id, status)
        except Exception as e:
            logger.warning(f"Natural session handling failed: {e}")
            status = tmux_manager.format_status()
            self.sender.send_text(sender_id, status)

    # ── Scheduled Task Management (approval flow) ──

    def _handle_schedule_request(self, text: str, sender_id: str, user_id: str):
        """Parse a schedule request from group chat and ask admin for approval."""
        user_name = self.contacts.get_name(user_id) if user_id else "群友"

        prompt = (
            "用户在群里请求了一个定时任务。解析消息，只输出一行 JSON：\n"
            '{"description":"简短描述","prompt":"要执行的具体指令","interval_min":数字,"one_shot":false}\n'
            "- interval_min: 执行间隔（分钟），每天=1440，每小时=60\n"
            "- one_shot: 是否只执行一次\n"
            "- prompt: 具体要 AI 做的事情（搜索、查价格、分析等）\n"
            "- 如果涉及股票监控，prompt 里要包含股票名称和代码\n\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            raw = raw.strip().strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
            parsed = json.loads(raw)
        except Exception as e:
            logger.warning(f"Schedule request parsing failed: {e}")
            self._add_turn("user", text, chat_id=sender_id, user_name=user_name)
            self._execute_claude_group(text, sender_id, user_id=user_id)
            return

        desc = parsed.get("description", text[:50])
        task_prompt = parsed.get("prompt", text)
        interval = parsed.get("interval_min", 60)
        one_shot = parsed.get("one_shot", False)

        req = task_scheduler.create_pending_request(
            description=desc,
            prompt=task_prompt,
            interval_min=interval,
            requested_by=user_id,
            requester_name=user_name,
            one_shot=one_shot,
        )

        interval_str = f"每{interval}分钟" if interval and not one_shot else "一次性"
        msg = (
            f"老板，{user_name} 想加个定时任务：\n\n"
            f"📌 {desc}\n"
            f"⏰ {interval_str}\n"
            f"📝 {task_prompt[:100]}\n\n"
            f"请求ID: {req['id']}\n"
            f"回复「同意」或「拒绝」"
        )
        self.sender.send_text_at(
            sender_id, msg,
            at_user_id=task_scheduler.ADMIN_OPEN_ID,
            at_user_name="老板",
        )

    def _handle_task_approval(self, sender_id: str):
        """Admin approved the latest pending task request."""
        latest = task_scheduler.get_latest_pending()
        if not latest:
            self.sender.send_text(sender_id, "没有待审批的定时任务请求")
            return

        task = task_scheduler.approve_pending(latest["id"])
        if not task:
            self.sender.send_text(sender_id, "审批失败，请求可能已过期")
            return

        interval_str = f"每{task['interval_min']}分钟" if task["interval_min"] and not task["one_shot"] else "一次性"
        requester = latest.get("requester_name", "群友")
        self.sender.send_text(
            sender_id,
            f"✅ 已批准并创建定时任务！\n\n"
            f"📌 {task['description']}\n"
            f"⏰ {interval_str}\n"
            f"👤 请求者: {requester}\n"
            f"🆔 任务ID: {task['id']}",
        )

    def _handle_task_rejection(self, sender_id: str):
        """Admin rejected the latest pending task request."""
        latest = task_scheduler.get_latest_pending()
        if not latest:
            self.sender.send_text(sender_id, "没有待审批的定时任务请求")
            return

        task_scheduler.reject_pending(latest["id"])
        requester = latest.get("requester_name", "群友")
        self.sender.send_text(
            sender_id,
            f"❌ 已拒绝 {requester} 的定时任务请求: {latest['description']}",
        )
