import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ERROR_LOG_FILE = Path("/Users/tuanyou/Happycode2026/vault/logs/error_log.json")
MAX_ERRORS = 500


class ErrorEntry:
    """Immutable error log entry."""

    def __init__(self, error_type: str, message: str, source: str,
                 severity: str = "medium", context: str = "",
                 timestamp: Optional[str] = None, resolved: bool = False,
                 resolution: str = ""):
        self.error_type = error_type
        self.message = message[:500]
        self.source = source
        self.severity = severity  # low, medium, high, critical
        self.context = context[:300]
        self.timestamp = timestamp or datetime.now().isoformat()
        self.resolved = resolved
        self.resolution = resolution

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "source": self.source,
            "severity": self.severity,
            "context": self.context,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }

    @staticmethod
    def from_dict(data: dict) -> "ErrorEntry":
        return ErrorEntry(
            error_type=data.get("error_type", "unknown"),
            message=data.get("message", ""),
            source=data.get("source", ""),
            severity=data.get("severity", "medium"),
            context=data.get("context", ""),
            timestamp=data.get("timestamp"),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution", ""),
        )


class ErrorTracker:
    """Structured error logging with analysis capabilities."""

    def __init__(self, log_file: Path = ERROR_LOG_FILE):
        self._log_file = log_file
        self._errors: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            if self._log_file.exists():
                return json.loads(self._log_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save(self):
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            # Keep only recent errors
            if len(self._errors) > MAX_ERRORS:
                self._errors = self._errors[-MAX_ERRORS:]
            self._log_file.write_text(
                json.dumps(self._errors, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save error log: {e}")

    def track(self, error_type: str, message: str, source: str,
              severity: str = "medium", context: str = "") -> ErrorEntry:
        """Record an error occurrence."""
        entry = ErrorEntry(
            error_type=error_type,
            message=message,
            source=source,
            severity=severity,
            context=context,
        )
        self._errors.append(entry.to_dict())
        self._save()
        logger.info(f"Error tracked [{severity}]: {error_type} in {source}")
        return entry

    def resolve(self, index: int, resolution: str):
        """Mark an error as resolved with explanation."""
        if 0 <= index < len(self._errors):
            self._errors[index]["resolved"] = True
            self._errors[index]["resolution"] = resolution[:300]
            self._save()

    def get_recent(self, count: int = 10, unresolved_only: bool = False) -> list[dict]:
        """Get recent errors."""
        errors = self._errors
        if unresolved_only:
            errors = [e for e in errors if not e.get("resolved")]
        return errors[-count:]

    def get_stats(self) -> dict:
        """Get error statistics by type and severity."""
        total = len(self._errors)
        unresolved = sum(1 for e in self._errors if not e.get("resolved"))
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_source: dict[str, int] = {}

        for e in self._errors:
            t = e.get("error_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            s = e.get("severity", "medium")
            by_severity[s] = by_severity.get(s, 0) + 1
            src = e.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total": total,
            "unresolved": unresolved,
            "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "by_severity": by_severity,
            "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])[:10]),
        }

    def get_recurring_patterns(self, min_count: int = 3) -> list[dict]:
        """Find recurring error patterns for auto-fix suggestions."""
        type_msgs: dict[str, list[dict]] = {}
        for e in self._errors:
            if e.get("resolved"):
                continue
            key = e.get("error_type", "unknown")
            type_msgs.setdefault(key, []).append(e)

        patterns = []
        for error_type, entries in type_msgs.items():
            if len(entries) >= min_count:
                patterns.append({
                    "error_type": error_type,
                    "count": len(entries),
                    "latest": entries[-1],
                    "sources": list({e.get("source", "") for e in entries}),
                })
        return sorted(patterns, key=lambda x: -x["count"])

    def resolve_by_type(self, error_type: str, resolution: str):
        """Mark all unresolved errors of a given type as resolved."""
        changed = False
        for e in self._errors:
            if e.get("error_type") == error_type and not e.get("resolved"):
                e["resolved"] = True
                e["resolution"] = resolution[:300]
                changed = True
        if changed:
            self._save()

    def auto_resolve_duplicates(self) -> int:
        """Resolve duplicate errors, keeping only the latest of each type unresolved."""
        seen: dict[str, int] = {}
        resolved_count = 0
        for i, e in enumerate(self._errors):
            if e.get("resolved"):
                continue
            key = f"{e.get('error_type')}:{e.get('source')}"
            if key in seen:
                self._errors[seen[key]]["resolved"] = True
                self._errors[seen[key]]["resolution"] = "auto-dedup: newer occurrence exists"
                resolved_count += 1
            seen[key] = i
        if resolved_count > 0:
            self._save()
        return resolved_count

    def get_fix_suggestions(self) -> list[dict]:
        """Generate fix suggestions based on known error patterns."""
        fixes = {
            "kb_query_error": {
                "check": "vector store database connectivity",
                "fix": "reindex vault: python scripts/reindex_vault.py",
                "auto": True,
            },
            "timeout": {
                "check": "Claude Code process hanging or overloaded",
                "fix": "reduce prompt size or increase timeout",
                "auto": False,
            },
            "execution_error": {
                "check": "Claude Code binary or environment issue",
                "fix": "verify claude binary exists and CLAUDECODE is unset",
                "auto": True,
            },
            "url_parse_error": {
                "check": "network or parser issue",
                "fix": "check network connectivity and parser implementation",
                "auto": False,
            },
            "intent_classify_error": {
                "check": "Claude API call for intent classification",
                "fix": "fallback to keyword-based classification",
                "auto": False,
            },
        }
        suggestions = []
        patterns = self.get_recurring_patterns(min_count=2)
        for p in patterns:
            fix_info = fixes.get(p["error_type"], {
                "check": "unknown error pattern",
                "fix": "investigate manually",
                "auto": False,
            })
            suggestions.append({
                "error_type": p["error_type"],
                "count": p["count"],
                "sources": p["sources"],
                **fix_info,
            })
        return suggestions

    def format_summary(self, count: int = 5) -> str:
        """Format recent errors as human-readable text."""
        recent = self.get_recent(count, unresolved_only=True)
        if not recent:
            return "No unresolved errors."

        lines = []
        for e in recent:
            status = "RESOLVED" if e.get("resolved") else e.get("severity", "").upper()
            ts = e.get("timestamp", "")[:16]
            lines.append(
                f"[{status}] {ts} | {e.get('error_type')} in {e.get('source')}\n"
                f"  {e.get('message', '')[:120]}"
            )
        return "\n".join(lines)
