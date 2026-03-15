"""IntentMixin — message patterns and RAG knowledge base query.

Provides regex patterns used by the message router for:
- Pending task completion detection
- Auto-feature disable detection
- Admin approval/rejection in group chat
- Schedule request detection in group chat
- RAG skip detection for trivial messages
"""

import logging
import re

logger = logging.getLogger(__name__)


class IntentMixin:
    """Message patterns + knowledge base RAG query."""

    # ── Patterns used by handle_message / _route_group ──

    _SCHEDULE_PATTERNS = re.compile(
        r"(每\s*\d+\s*分钟|每\s*\d+\s*小时|每天|每日|每周|定时.*(?:查|看|监控|提醒|发|推)"
        r"|帮我.*(?:盯|监控|提醒|定时)|(?:分钟|小时).*(?:一次|提醒|推送|查看))"
    )
    _APPROVAL_PATTERNS = re.compile(
        r"^(同意|批准|approve|ok|可以|行|准了|通过|yes)\s*$", re.IGNORECASE
    )
    _REJECT_PATTERNS = re.compile(
        r"^(拒绝|不行|reject|no|否|算了|不用)\s*$", re.IGNORECASE
    )
    _TASK_DONE_PATTERNS = re.compile(
        r"^(搞定了|完成了|做完了|弄好了|ok了|已完成|done|不用了|算了|取消吧)\s*$",
        re.IGNORECASE,
    )
    _DISABLE_PATTERN_RE = re.compile(
        r"(不要自动|关闭自动|别自动|停止自动)(分析|拆分|处理|执行|回复)",
    )

    # ── RAG skip: trivial messages that don't need knowledge base lookup ──

    _SKIP_RAG_PATTERNS = re.compile(
        r"^(你好|hi|hello|ok|好的|嗯嗯?|哈哈+|谢谢|感谢|666+|牛|👍|😂|😄|🤣|"
        r"行|收到|了解|明白|是的|对的|可以|没问题|好嘞|好哒|"
        r"好的[，,]?谢谢[！!]?|谢谢[啦了哈]?[！!]?|辛苦了?|"
        r"哈哈哈+|笑死|太强了|厉害|6+|赞|对|嘿|哦|噢|啊|呵呵"
        r")[！!。.～~]?$",
        re.IGNORECASE,
    )

    def _query_knowledge_base(self, text: str, chat_type: str = "p2p") -> str:
        """Query vector store for relevant articles to inject as context."""
        min_len = 10 if chat_type == "group" else 6
        if len(text) < min_len or self._SKIP_RAG_PATTERNS.match(text.strip()):
            return ""
        try:
            results = self.vector_store.query_similar(text, top_k=3)
            if not results:
                return ""
            context_parts = []
            for r in results:
                if not r:
                    continue
                if r.get("distance", 1) < 0.7:
                    title = r.get("title", "")
                    summary = r.get("summary", "")
                    if title or summary:
                        context_parts.append(f"- {title}: {summary}")
            if not context_parts:
                return ""
            return "相关知识库内容：\n" + "\n".join(context_parts)
        except Exception as e:
            logger.warning(f"Knowledge base query failed, falling back to keyword search: {e}")
            self.error_tracker.track(
                "kb_query_error", str(e), "query_knowledge_base", "medium", text[:100],
            )
            return self._keyword_fallback(text)

    def _keyword_fallback(self, text: str, max_results: int = 3) -> str:
        """Fallback keyword search when vector store is unavailable.

        Scans vault article/social/docs titles and first 500 chars for keyword matches.
        """
        from pathlib import Path
        try:
            vault = Path(getattr(self, '_vault_path', '/Users/tuanyou/Happycode2026/vault'))
            # Extract keywords (2+ char Chinese/English words)
            keywords = [w for w in re.split(r'[\s,，。？！、/]+', text) if len(w) >= 2]
            if not keywords:
                return ""

            hits = []
            for subdir in ("articles", "social", "docs"):
                d = vault / subdir
                if not d.exists():
                    continue
                for md in d.glob("*.md"):
                    try:
                        content = md.read_text(encoding="utf-8")[:500]
                        title = md.stem.replace("-", " ").replace("_", " ")
                        searchable = f"{title} {content}".lower()
                        score = sum(1 for kw in keywords if kw.lower() in searchable)
                        if score > 0:
                            hits.append((score, title, content[:150]))
                    except Exception:
                        continue

            if not hits:
                return ""
            hits.sort(key=lambda x: x[0], reverse=True)
            parts = [f"- {title}: {snippet}..." for _, title, snippet in hits[:max_results]]
            logger.info(f"Keyword fallback found {len(hits)} results for: {text[:50]}")
            return "相关知识库内容（关键词匹配）：\n" + "\n".join(parts)
        except Exception as e:
            logger.warning(f"Keyword fallback also failed: {e}")
            return ""
