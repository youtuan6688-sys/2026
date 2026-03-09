import json
import logging

import anthropic

from config.prompts import ANALYSIS_PROMPT, RELATION_PROMPT
from config.settings import Settings
from src.models.content import ParsedContent, AnalyzedContent

logger = logging.getLogger(__name__)


class AIAnalyzer:
    def __init__(self, settings: Settings, vector_store=None):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.max_length = settings.max_content_length
        self.vector_store = vector_store

    def analyze(self, content: ParsedContent) -> AnalyzedContent:
        """Run AI analysis: generate tags, summary, category, and find related content."""
        # Step 1: Tags + Summary + Category
        analysis = self._analyze_content(content)

        # Step 2: Find related content via vector similarity
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

    def _analyze_content(self, content: ParsedContent) -> dict:
        """Call Claude API to analyze content."""
        text = content.content[:self.max_length]
        prompt = ANALYSIS_PROMPT.format(
            title=content.title,
            platform=content.platform,
            text=text,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text.strip()

            # Handle potential markdown fences
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            return json.loads(result_text)
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

        # Use Claude to evaluate which are truly related
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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            relations = json.loads(result_text)

            # Enrich with titles
            id_to_title = {s["id"]: s.get("title", "") for s in similar}
            for r in relations:
                r["title"] = id_to_title.get(r["id"], "")

            return relations
        except Exception as e:
            logger.warning(f"Relation analysis failed: {e}")
            return []
