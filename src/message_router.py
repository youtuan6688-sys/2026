import logging

from src.utils.url_utils import extract_urls, detect_platform
from src.parsers import get_parser
from src.ai.analyzer import AIAnalyzer
from src.storage.obsidian_writer import ObsidianWriter
from src.storage.content_index import ContentIndex

logger = logging.getLogger(__name__)


class MessageRouter:
    def __init__(self, ai_analyzer: AIAnalyzer, writer: ObsidianWriter, index: ContentIndex):
        self.ai_analyzer = ai_analyzer
        self.writer = writer
        self.index = index

    def handle_message(self, sender_id: str, text: str, raw_message=None):
        """Process an incoming message: extract URLs, parse, analyze, save."""
        urls = extract_urls(text)

        if not urls:
            logger.info(f"No URLs found in message: {text[:100]}")
            return

        for url in urls:
            try:
                self._process_url(url)
            except Exception as e:
                logger.error(f"Failed to process URL {url}: {e}", exc_info=True)

    def _process_url(self, url: str):
        # Deduplication
        if self.index.exists(url):
            logger.info(f"URL already saved, skipping: {url}")
            return

        # Detect platform and parse
        platform = detect_platform(url)
        parser = get_parser(platform)
        logger.info(f"Parsing [{platform}]: {url}")

        parsed = parser.parse(url)
        if not parsed.content and not parsed.title:
            logger.warning(f"No content extracted from {url}")
            return

        # AI analysis
        logger.info(f"Analyzing: {parsed.title}")
        analyzed = self.ai_analyzer.analyze(parsed)

        # Save to Obsidian vault
        filepath = self.writer.save(analyzed)
        logger.info(f"Saved to: {filepath}")
