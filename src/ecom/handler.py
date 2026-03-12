"""E-commerce AI handler — /ecom command for Feishu bot.

Provides 6 e-commerce AI capabilities:
- 爆款拆解, 市场调研, 极限词检测, 多平台文案, 直播策划, 短视频脚本
"""

import json
import logging
import threading

import httpx

from config.ecom_prompts import ECOM_PROMPTS, resolve_scene, get_prompt
from config.settings import settings

logger = logging.getLogger(__name__)


class EcomHandler:
    """Handle /ecom commands for e-commerce AI processing."""

    def __init__(self, sender, bitable_manager=None):
        self.sender = sender
        self.bitable_manager = bitable_manager

    def _call_deepseek(self, prompt: str, max_tokens: int = 4000) -> str:
        """Call DeepSeek API for e-commerce AI processing."""
        try:
            resp = httpx.post(
                f"{settings.ai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                json={
                    "model": settings.ai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"DeepSeek call failed: {e}")
            return ""

    def handle_command(self, command: str, sender_id: str) -> None:
        """Handle /ecom commands.

        Usage:
            /ecom                     — show help
            /ecom list                — list all scenes
            /ecom <场景> <内容>        — run AI analysis
            /ecom batch <场景> <内容>  — batch process (multiline)
        """
        parts = command.strip().split(maxsplit=2)

        if len(parts) < 2:
            self._send_help(sender_id)
            return

        sub = parts[1].strip()
        args = parts[2] if len(parts) > 2 else ""

        if sub in ("help", "帮助"):
            self._send_help(sender_id)
        elif sub in ("list", "场景", "模板"):
            self._list_scenes(sender_id)
        elif sub == "batch":
            self._cmd_batch(args, sender_id)
        elif sub == "setup":
            self._cmd_setup(sender_id)
        elif sub == "scan":
            self._cmd_scan(args, sender_id)
        else:
            # Try to resolve sub as scene name
            scene = resolve_scene(sub)
            if scene:
                content = args
                if not content:
                    self.sender.send_text(
                        sender_id,
                        f"用法: /ecom {sub} <内容>\n"
                        f"例如: /ecom {sub} 某品牌面膜产品介绍...",
                    )
                    return
                self._cmd_process(scene, content, sender_id)
            else:
                # Treat entire text after /ecom as content, auto-detect scene
                full_text = command[len("/ecom"):].strip()
                self._cmd_auto_detect(full_text, sender_id)

    def _cmd_process(self, scene: str, content: str, sender_id: str) -> None:
        """Process content with specified scene prompt."""
        desc = ECOM_PROMPTS[scene]["desc"]
        self.sender.send_text(
            sender_id,
            f"正在用「{scene}」分析...\n场景: {desc}\n内容长度: {len(content)} 字",
        )

        thread = threading.Thread(
            target=self._process_pipeline,
            args=(scene, content, sender_id),
            daemon=True,
        )
        thread.start()

    def _process_pipeline(self, scene: str, content: str, sender_id: str) -> None:
        """Background AI processing pipeline."""
        try:
            prompt = get_prompt(scene, content)
            if prompt is None:
                self.sender.send_text(sender_id, f"场景「{scene}」未找到")
                return

            result = self._call_deepseek(prompt)

            if not result:
                self.sender.send_text(sender_id, f"「{scene}」分析失败，AI 无返回")
                return

            # Try to parse and pretty-format JSON
            display = self._format_result(scene, result)
            self.sender.send_text(sender_id, display)

        except Exception as e:
            logger.exception(f"Ecom process error: {e}")
            self.sender.send_text(sender_id, f"处理异常: {str(e)[:300]}")

    def _cmd_auto_detect(self, text: str, sender_id: str) -> None:
        """Auto-detect which scene fits best based on content."""
        # Simple keyword matching for auto-detection
        detection_rules = [
            ("极限词检测", ["检测", "合规", "违禁", "极限词", "广告法"]),
            ("爆款拆解", ["拆解", "爆款", "口播", "分析这个视频", "分析这条"]),
            ("市场调研", ["调研", "趋势", "市场", "品类", "竞品", "分析行业"]),
            ("多平台文案", ["文案", "种草", "带货", "详情页", "写文案"]),
            ("直播策划", ["直播", "策划", "复盘", "GMV"]),
            ("短视频脚本", ["脚本", "分镜", "拍摄", "短视频"]),
        ]

        detected = None
        for scene, keywords in detection_rules:
            if any(kw in text for kw in keywords):
                detected = scene
                break

        if detected:
            self._cmd_process(detected, text, sender_id)
        else:
            # Default to multi-platform copy if no match
            self.sender.send_text(
                sender_id,
                "未识别到具体场景，请指定:\n"
                "/ecom <场景名> <内容>\n\n"
                "发 /ecom list 查看可用场景",
            )

    def _cmd_batch(self, args: str, sender_id: str) -> None:
        """Batch process: /ecom batch <场景>\n<内容1>\n<内容2>..."""
        lines = args.strip().split("\n", 1)
        if len(lines) < 2:
            self.sender.send_text(
                sender_id,
                "用法: /ecom batch <场景名>\n内容1\n内容2\n...\n"
                "每行一条内容，批量处理",
            )
            return

        scene_name = lines[0].strip()
        scene = resolve_scene(scene_name)
        if not scene:
            self.sender.send_text(
                sender_id, f"未知场景: {scene_name}\n发 /ecom list 查看可用场景"
            )
            return

        items = [line.strip() for line in lines[1].split("\n") if line.strip()]
        if not items:
            self.sender.send_text(sender_id, "未检测到内容行")
            return

        if len(items) > 10:
            self.sender.send_text(sender_id, f"最多批量处理 10 条，你发了 {len(items)} 条")
            return

        self.sender.send_text(
            sender_id,
            f"批量「{scene}」处理 {len(items)} 条内容...",
        )

        thread = threading.Thread(
            target=self._batch_pipeline,
            args=(scene, items, sender_id),
            daemon=True,
        )
        thread.start()

    def _batch_pipeline(self, scene: str, items: list[str], sender_id: str) -> None:
        """Background batch processing."""
        try:
            succeeded = 0

            for i, content in enumerate(items, 1):
                self.sender.send_text(
                    sender_id, f"[{i}/{len(items)}] 处理中..."
                )
                prompt = get_prompt(scene, content)
                if prompt is None:
                    continue

                result = self._call_deepseek(prompt)
                if result:
                    display = self._format_result(scene, result)
                    self.sender.send_text(
                        sender_id, f"[{i}/{len(items)}] 结果:\n{display}"
                    )
                    succeeded += 1
                else:
                    self.sender.send_text(
                        sender_id, f"[{i}/{len(items)}] 处理失败"
                    )

            self.sender.send_text(
                sender_id,
                f"批量完成: {succeeded}/{len(items)} 成功",
            )

        except Exception as e:
            logger.exception(f"Ecom batch error: {e}")
            self.sender.send_text(sender_id, f"批量处理异常: {str(e)[:300]}")

    # ── Bitable Template & Auto-scan ──

    # Standard field definitions for e-commerce marketing bitable
    ECOM_TABLE_FIELDS = {
        "商品信息表": [
            ("商品名称", 1),      # Text
            ("品类", 3),          # SingleSelect
            ("产品描述", 1),      # Text
            ("卖点", 1),          # Text
            ("价格区间", 1),      # Text
            ("目标人群", 1),      # Text
            ("天猫文案", 1),      # Text — AI generated
            ("小红书文案", 1),    # Text — AI generated
            ("抖音脚本", 1),      # Text — AI generated
            ("投流文案", 1),      # Text — AI generated
            ("极限词检测", 1),    # Text — AI generated
            ("风险等级", 3),      # SingleSelect
            ("处理状态", 3),      # SingleSelect
        ],
    }

    # AI prompts for auto-processing fields
    FIELD_PROMPTS = {
        "天猫文案": (
            "根据以下产品描述，写一段天猫/淘宝详情页文案（300-500字），"
            "要求专业、信任背书、卖点突出。直接输出文案，不要 JSON。\n\n产品信息：{content}"
        ),
        "小红书文案": (
            "根据以下产品描述，写一篇小红书种草笔记（200-400字），"
            "要求生活化、有共鸣、软种草，带 emoji 和话题标签。直接输出文案。\n\n产品信息：{content}"
        ),
        "抖音脚本": (
            "根据以下产品描述，写一个 55-65 秒的抖音口播脚本，"
            "包含钩子（前3秒）、痛点、解决方案、行动号召。直接输出脚本。\n\n产品信息：{content}"
        ),
        "投流文案": (
            "根据以下产品描述，写 3 条投流广告文案（每条≤50字），"
            "要求卖点前置、强CTA。直接输出 3 条，换行分隔。\n\n产品信息：{content}"
        ),
        "极限词检测": (
            "检测以下文案中的广告法违禁词/极限词。"
            "输出格式：\n违规词 → 建议替换\n如无违规，输出「合规，无违禁词」。\n\n文案：{content}"
        ),
    }

    def _cmd_setup(self, sender_id: str) -> None:
        """Create standard e-commerce marketing bitable template."""
        if not self.bitable_manager:
            self.sender.send_text(sender_id, "Bitable 管理器未初始化")
            return

        self.sender.send_text(sender_id, "正在创建电商营销多维表格模板...")

        thread = threading.Thread(
            target=self._setup_pipeline,
            args=(sender_id,),
            daemon=True,
        )
        thread.start()

    def _setup_pipeline(self, sender_id: str) -> None:
        """Background: create bitable app with pre-defined tables."""
        try:
            bm = self.bitable_manager

            # Create bitable app
            app = bm.create_app("电商营销管理系统")
            if not app:
                self.sender.send_text(sender_id, "创建多维表格失败")
                return

            app_token = app["app_token"]
            url = app["url"]

            # List default table (bitable creates one by default)
            tables = bm.list_tables(app_token)

            # Create our table (or rename default)
            table = bm.create_table(app_token, "商品信息表")
            if not table:
                self.sender.send_text(
                    sender_id,
                    f"表格创建失败，但多维表格已创建: {url}",
                )
                return

            self.sender.send_text(
                sender_id,
                f"电商营销多维表格已创建!\n\n"
                f"链接: {url}\n"
                f"数据表: 商品信息表\n\n"
                f"字段说明:\n"
                f"  手动填写: 商品名称、品类、产品描述、卖点、价格区间、目标人群\n"
                f"  AI自动生成: 天猫文案、小红书文案、抖音脚本、投流文案、极限词检测\n\n"
                f"填写产品描述后，用 /ecom scan {app_token} 触发 AI 自动生成文案",
            )

        except Exception as e:
            logger.exception(f"Ecom setup error: {e}")
            self.sender.send_text(sender_id, f"创建异常: {str(e)[:300]}")

    def _cmd_scan(self, args: str, sender_id: str) -> None:
        """Scan bitable records and auto-generate AI fields.

        Usage: /ecom scan <app_token_or_url> [table_id]
        """
        if not self.bitable_manager:
            self.sender.send_text(sender_id, "Bitable 管理器未初始化")
            return

        parts = args.strip().split()
        if not parts:
            self.sender.send_text(
                sender_id,
                "用法: /ecom scan <多维表格链接或app_token>\n"
                "扫描未处理的商品记录，自动生成文案",
            )
            return

        app_token = parts[0]
        self.sender.send_text(sender_id, "正在扫描未处理记录...")

        thread = threading.Thread(
            target=self._scan_pipeline,
            args=(app_token, sender_id),
            daemon=True,
        )
        thread.start()

    def _scan_pipeline(self, app_token: str, sender_id: str) -> None:
        """Background: scan and AI-process unprocessed bitable records."""
        try:
            bm = self.bitable_manager
            app_token = bm.extract_app_token(app_token)

            # Find the table
            tables = bm.list_tables(app_token)
            if not tables:
                self.sender.send_text(sender_id, "未找到数据表")
                return

            # Use first table or find "商品信息表"
            table_id = None
            for t in tables:
                if "商品" in t["name"] or "产品" in t["name"]:
                    table_id = t["table_id"]
                    break
            if not table_id:
                table_id = tables[0]["table_id"]

            # Use ai_process_batch
            stats = bm.ai_process_batch(
                app_token, table_id,
                source_field="产品描述",
                target_fields=self.FIELD_PROMPTS,
                filter_field="天猫文案",  # Process records where this is empty
                max_records=20,
            )

            self.sender.send_text(
                sender_id,
                f"扫描完成!\n"
                f"  处理成功: {stats['processed']} 条\n"
                f"  处理失败: {stats['failed']} 条\n"
                f"  跳过(无描述): {stats['skipped']} 条",
            )

        except Exception as e:
            logger.exception(f"Ecom scan error: {e}")
            self.sender.send_text(sender_id, f"扫描异常: {str(e)[:300]}")

    def _format_result(self, scene: str, raw_result: str) -> str:
        """Format AI result for chat display."""
        # Try to extract JSON from result
        try:
            # Strip markdown code blocks if present
            cleaned = raw_result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            data = json.loads(cleaned)
            # Pretty-print with Chinese-friendly formatting
            formatted = json.dumps(data, ensure_ascii=False, indent=2)
            return f"【{scene}】分析结果:\n\n{formatted}"
        except (json.JSONDecodeError, ValueError):
            # If not valid JSON, return raw with header
            return f"【{scene}】分析结果:\n\n{raw_result}"

    def _list_scenes(self, sender_id: str) -> None:
        """List all available e-commerce scenes."""
        lines = ["电商 AI 场景模板:\n"]
        for name, info in ECOM_PROMPTS.items():
            aliases = ", ".join(info["alias"])
            lines.append(f"  {name} — {info['desc']}")
            lines.append(f"    别名: {aliases}")
        lines.append(f"\n共 {len(ECOM_PROMPTS)} 个场景")
        lines.append("用法: /ecom <场景名> <内容>")
        self.sender.send_text(sender_id, "\n".join(lines))

    def _send_help(self, sender_id: str) -> None:
        self.sender.send_text(
            sender_id,
            "电商 AI 助手:\n\n"
            "  /ecom <场景> <内容>  — AI分析处理\n"
            "  /ecom 极限词检测 <文案> — 广告法合规检测\n"
            "  /ecom 多平台文案 <产品信息> — 一键生成4平台文案\n"
            "  /ecom 爆款拆解 <口播稿> — 拆解爆款元素\n"
            "  /ecom 市场调研 <主题> — 品类趋势分析\n"
            "  /ecom 直播策划 <产品> — 直播脚本策划\n"
            "  /ecom 短视频脚本 <主题> — 分镜脚本生成\n"
            "  /ecom batch <场景> — 批量处理\n"
            "  /ecom list — 查看所有场景\n\n"
            "多维表格集成:\n"
            "  /ecom setup — 创建电商营销多维表格模板\n"
            "  /ecom scan <链接> — 扫描未处理记录，AI自动生成文案\n\n"
            "场景支持别名: 如 /ecom 文案 <产品> 等价于 /ecom 多平台文案 <产品>",
        )
