import json
import logging
import os
import subprocess

from config.prompts import ANALYSIS_PROMPT, RELATION_PROMPT
from config.settings import Settings
from src.models.content import ParsedContent, AnalyzedContent

logger = logging.getLogger(__name__)

CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"

ANALYSIS_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["tech", "business", "lifestyle", "culture", "science",
                     "design", "finance", "health", "education", "other"],
        },
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tags", "summary", "category", "key_points"],
})

RELATION_SCHEMA = json.dumps({
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["id", "reason"],
    },
})


class AIAnalyzer:
    def __init__(self, settings: Settings, vector_store=None):
        self.max_length = settings.max_content_length
        self.vector_store = vector_store

    def analyze(self, content: ParsedContent) -> AnalyzedContent:
        """Run AI analysis: generate tags, summary, category, and find related content."""
        analysis = self._analyze_content(content)

        related = []
        if self.vector_store:
            try:
                related = self._find_related(analysis, content)
            except Exception as e:
                logger.warning(f"Failed to find related content: {e}")

        return AnalyzedContent(
            parsed=content,
            tags=analysis.get("tags", []),
            summary=analysis.get("summary", ""),
            category=analysis.get("category", "other"),
            key_points=analysis.get("key_points", []),
            related=related,
        )

    def _call_ai(self, prompt: str, json_schema: str = "") -> dict | list | str:
        """Call Claude Code CLI with optional structured JSON output.

        When json_schema is provided, uses --output-format json + --json-schema
        and returns the parsed structured_output directly.
        Otherwise returns raw text output.
        """
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        cmd = [
            CLAUDE_PATH, "-p", prompt,
            "--model", "sonnet",
        ]

        if json_schema:
            cmd.extend(["--output-format", "json", "--json-schema", json_schema])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/Users/tuanyou",
            env=env,
        )

        if result.returncode != 0:
            logger.warning(f"Claude CLI stderr: {result.stderr[:300]}")

        stdout = result.stdout.strip()

        if json_schema and stdout:
            envelope = json.loads(stdout)
            structured = envelope.get("structured_output")
            if structured is not None:
                return structured
            # Fallback: parse result text if structured_output missing
            return self._parse_json_response(envelope.get("result", ""))

        return stdout

    def _parse_json_response(self, text: str) -> dict | list:
        """Parse JSON from AI response, handling markdown fences."""
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    def _analyze_content(self, content: ParsedContent) -> dict:
        """Call AI to analyze content."""
        text = content.content[:self.max_length]
        if content.images:
            img_list = "\n".join(content.images[:5])
            text += f"\n\n[附带图片]\n{img_list}"
        prompt = ANALYSIS_PROMPT.format(
            title=content.title,
            platform=content.platform,
            text=text,
        )

        try:
            return self._call_ai(prompt, json_schema=ANALYSIS_SCHEMA)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return {"tags": [], "summary": content.title, "category": "other", "key_points": []}
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {"tags": [], "summary": content.title, "category": "other", "key_points": []}

    def _find_related(self, analysis: dict, content: ParsedContent) -> list[dict]:
        """Find related content using vector similarity."""
        similar = self.vector_store.query_similar(content.content, top_k=5)
        if not similar:
            return []

        summaries_text = "\n".join(
            f"- id: {s['id']}, 标题: {s.get('title', '未知')}, 摘要: {s.get('summary', '')}"
            for s in similar
        )

        prompt = RELATION_PROMPT.format(
            new_title=content.title,
            new_summary=analysis.get("summary", ""),
            new_tags=", ".join(analysis.get("tags", [])),
            existing_summaries=summaries_text,
        )

        try:
            relations = self._call_ai(prompt, json_schema=RELATION_SCHEMA)

            id_to_title = {s["id"]: s.get("title", "") for s in similar}
            for r in relations:
                r["title"] = id_to_title.get(r["id"], "")

            return relations
        except Exception as e:
            logger.warning(f"Relation analysis failed: {e}")
            return []
