import logging
import re

from src.parsers.base import BaseParser
from src.parsers.generic_web import GenericWebParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class FeishuDocParser(BaseParser):
    """Parser for Feishu/Lark documents.

    For v1, falls back to generic web parsing for public links.
    TODO: Use lark-oapi docx API for authenticated access to private docs.
    """

    def parse(self, url: str) -> ParsedContent:
        try:
            result = GenericWebParser().parse(url)
            result.platform = "feishu"
            return result
        except Exception as e:
            logger.warning(f"Feishu doc parse failed: {e}")
            return ParsedContent(
                url=url,
                platform="feishu",
                title="飞书文档",
                content=f"[需要登录查看: {url}]",
            )
