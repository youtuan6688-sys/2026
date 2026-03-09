"""Claude API quota tracking with auto-degradation to DeepSeek.

Tracks per-model usage, detects rate limits from CLI output,
auto-learns thresholds, and switches to DeepSeek when approaching limits.

Opus and Sonnet have independent quota pools (since Nov 2025).
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"
QUOTA_FILE = Path("/Users/tuanyou/Happycode2026/data/quota_state.json")
DEGRADE_THRESHOLD = 0.80  # Switch to backup at 80% of learned limit

# Cooldown durations (seconds)
COOLDOWN_STALE = 900       # 15 min for stale/transient rate limits
COOLDOWN_CONFIRMED = 7200  # 2 hours for confirmed rate limits

# Rate limit signature in Claude CLI output
RATE_LIMIT_PHRASES = [
    "hit your limit",
    "rate limit",
    "too many requests",
    "overloaded",
]

# Don't learn limits below these thresholds (likely stale rate limits)
MIN_RELIABLE_LIMIT = {
    "haiku": 20,
    "sonnet": 10,
    "opus": 5,
}


class QuotaTracker:
    """Track Claude API usage per model and auto-degrade to DeepSeek."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = self._load_state()

    def _load_state(self) -> dict:
        """Load quota state from disk."""
        try:
            if QUOTA_FILE.exists():
                state = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
                # Reset counts if date changed
                if state.get("date") != date.today().isoformat():
                    state = self._fresh_state(state.get("learned_limits", {}))
                # Migrate legacy boolean rate_limited to string format
                for model in ("haiku", "sonnet", "opus"):
                    val = state.get("rate_limited", {}).get(model)
                    if isinstance(val, bool):
                        state.setdefault("rate_limited", {})[model] = ""
                return state
        except Exception as e:
            logger.warning(f"Failed to load quota state: {e}")
        return self._fresh_state({})

    def _fresh_state(self, learned_limits: dict) -> dict:
        return {
            "date": date.today().isoformat(),
            "calls": {"haiku": 0, "sonnet": 0, "opus": 0},
            "hourly_calls": {},  # {"haiku:14": 3, "sonnet:14": 5, ...}
            # rate_limited stores ISO timestamp when limit was hit (empty = not limited)
            "rate_limited": {"haiku": "", "sonnet": "", "opus": ""},
            "count_at_limit": {},  # how many calls when rate limit was hit
            "learned_limits": learned_limits,  # {"haiku": 200, "sonnet": 50, ...}
            "learned_hourly_limits": {},  # {"sonnet": 8, ...}
        }

    def _save_state(self):
        """Persist quota state to disk."""
        try:
            QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
            QUOTA_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save quota state: {e}")

    def _is_rate_limited_output(self, output: str) -> bool:
        """Check if Claude CLI output indicates a rate limit."""
        lower = output.lower()
        return any(phrase in lower for phrase in RATE_LIMIT_PHRASES)

    def _cooldown_for(self, model: str) -> int:
        """Return cooldown duration based on whether the limit was reliable."""
        count_at_limit = self._state.get("count_at_limit", {}).get(model, 0)
        min_reliable = MIN_RELIABLE_LIMIT.get(model, 10)
        if count_at_limit >= min_reliable:
            return COOLDOWN_CONFIRMED
        return COOLDOWN_STALE

    def _is_still_rate_limited(self, model: str) -> bool:
        """Check if rate limit is still active (cooldown depends on reliability)."""
        ts_str = self._state["rate_limited"].get(model, "")
        if not ts_str:
            return False
        # Handle legacy boolean format — clear it
        if isinstance(ts_str, bool):
            self._state["rate_limited"][model] = ""
            self._save_state()
            return False
        try:
            hit_time = datetime.fromisoformat(ts_str)
            elapsed = (datetime.now() - hit_time).total_seconds()
            cooldown = self._cooldown_for(model)
            if elapsed > cooldown:
                self._state["rate_limited"][model] = ""
                self._save_state()
                logger.info(
                    f"Rate limit for {model} expired after {elapsed/60:.0f}min "
                    f"(cooldown was {cooldown/60:.0f}min), retrying Claude"
                )
                return False
            remaining = (cooldown - elapsed) / 60
            logger.debug(f"{model} still rate-limited, {remaining:.0f}min remaining")
            return True
        except Exception:
            return False

    def should_use_backup(self, model: str) -> bool:
        """Check if we should use DeepSeek instead of Claude for this model."""
        with self._lock:
            # Recently hit rate limit (cooldown depends on stale vs confirmed)
            if self._is_still_rate_limited(model):
                return True

            # Check against learned daily threshold
            limit = self._state["learned_limits"].get(model)
            if limit and limit > 0:
                used = self._state["calls"].get(model, 0)
                if used >= int(limit * DEGRADE_THRESHOLD):
                    logger.info(
                        f"Daily quota approaching for {model}: "
                        f"{used}/{limit} ({used/limit:.0%}), switching to backup"
                    )
                    return True

            # Check against learned hourly threshold
            hourly_limit = self._state.get("learned_hourly_limits", {}).get(model)
            if hourly_limit and hourly_limit > 0:
                hourly_used = self._hourly_count(model)
                if hourly_used >= int(hourly_limit * DEGRADE_THRESHOLD):
                    logger.info(
                        f"Hourly quota approaching for {model}: "
                        f"{hourly_used}/{hourly_limit} this hour, switching to backup"
                    )
                    return True

            return False

    def _current_hour_key(self, model: str) -> str:
        return f"{model}:{datetime.now().hour}"

    def _hourly_count(self, model: str) -> int:
        key = self._current_hour_key(model)
        return self._state.get("hourly_calls", {}).get(key, 0)

    def record_call(self, model: str, success: bool, output: str = ""):
        """Record a Claude API call result (daily + hourly)."""
        with self._lock:
            self._state["calls"][model] = self._state["calls"].get(model, 0) + 1

            # Hourly tracking
            hourly = self._state.setdefault("hourly_calls", {})
            hkey = self._current_hour_key(model)
            hourly[hkey] = hourly.get(hkey, 0) + 1

            if not success or self._is_rate_limited_output(output):
                current_count = self._state["calls"][model]
                hourly_count = hourly[hkey]
                self._state["rate_limited"][model] = datetime.now().isoformat()
                self._state.setdefault("count_at_limit", {})[model] = current_count

                # Learn daily limit
                min_limit = MIN_RELIABLE_LIMIT.get(model, 10)
                if current_count >= min_limit:
                    old_limit = self._state["learned_limits"].get(model)
                    if old_limit is None or current_count < old_limit:
                        self._state["learned_limits"][model] = current_count
                        logger.warning(
                            f"Rate limit hit for {model} at {current_count} calls. "
                            f"Learned daily limit: {current_count}"
                        )
                else:
                    logger.warning(
                        f"Rate limit hit for {model} at {current_count} daily / "
                        f"{hourly_count} hourly calls "
                        f"(below min threshold {min_limit}, likely stale — not learning)"
                    )

                # Learn hourly limit (always learn — hourly limits are smaller)
                old_hourly = self._state.setdefault("learned_hourly_limits", {}).get(model)
                if old_hourly is None or hourly_count < old_hourly:
                    self._state["learned_hourly_limits"][model] = hourly_count
                    logger.info(f"Learned hourly limit for {model}: {hourly_count}")

            self._save_state()

    def _run_claude_subprocess(self, prompt: str, model: str,
                               timeout: int, cwd: str,
                               extra_args: list | None) -> tuple[str, bool]:
        """Execute Claude CLI subprocess. Returns (output, is_rate_limited)."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"

        cmd = [CLAUDE_PATH, "-p", prompt, "--model", model]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=env,
        )
        output = result.stdout.strip()
        is_limited = self._is_rate_limited_output(output)
        return output, is_limited

    def call_claude(self, prompt: str, model: str,
                    timeout: int = 60, cwd: str = "/Users/tuanyou/Happycode2026",
                    extra_args: list = None) -> str:
        """Call Claude CLI with retry-once and auto-degradation to DeepSeek.

        On rate limit: waits 5s and retries once before falling back.
        """
        # Check if we should use backup
        if model != "opus" and self.should_use_backup(model):
            logger.info(f"Using DeepSeek backup for {model} task")
            return self._call_deepseek(prompt)

        try:
            output, is_limited = self._run_claude_subprocess(
                prompt, model, timeout, cwd, extra_args,
            )
            self.record_call(model, success=not is_limited, output=output)

            if is_limited:
                if model == "opus":
                    logger.warning("Opus rate limited, no fallback available")
                    return ""

                # Retry once after 5s pause (handles transient 429s)
                logger.info(f"{model} rate limited, retrying in 5s...")
                time.sleep(5)
                output2, is_limited2 = self._run_claude_subprocess(
                    prompt, model, timeout, cwd, extra_args,
                )
                self.record_call(model, success=not is_limited2, output=output2)

                if is_limited2:
                    logger.info(f"{model} still limited after retry, falling back to DeepSeek")
                    return self._call_deepseek(prompt)
                return output2

            return output

        except subprocess.TimeoutExpired:
            self.record_call(model, success=False)
            raise
        except Exception as e:
            self.record_call(model, success=False)
            raise

    def _call_deepseek(self, prompt: str) -> str:
        """Call DeepSeek API as fallback."""
        try:
            resp = httpx.post(
                f"{settings.ai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                json={
                    "model": settings.ai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"DeepSeek fallback failed: {e}")
            return ""

    def get_stats(self) -> dict:
        """Get current quota stats for status display."""
        with self._lock:
            hour = datetime.now().hour
            hourly_this_hour = {
                model: self._state.get("hourly_calls", {}).get(f"{model}:{hour}", 0)
                for model in ("haiku", "sonnet", "opus")
            }
            stats = {
                "date": self._state["date"],
                "calls": dict(self._state["calls"]),
                "hourly_calls": hourly_this_hour,
                "rate_limited": {
                    k: v for k, v in self._state["rate_limited"].items() if v
                },
                "learned_limits": dict(self._state["learned_limits"]),
                "learned_hourly_limits": dict(
                    self._state.get("learned_hourly_limits", {})
                ),
            }
            return stats
