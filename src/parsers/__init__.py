from src.parsers.base import BaseParser
from src.parsers.generic_web import GenericWebParser
from src.parsers.wechat_article import WechatArticleParser
from src.parsers.twitter import TwitterParser
from src.parsers.xiaohongshu import XiaohongshuParser
from src.parsers.douyin import DouyinParser
from src.parsers.feishu_doc import FeishuDocParser

_PARSER_MAP: dict[str, BaseParser] = {
    "generic": GenericWebParser(),
    "wechat": WechatArticleParser(),
    "twitter": TwitterParser(),
    "xiaohongshu": XiaohongshuParser(),
    "douyin": DouyinParser(),
    "feishu": FeishuDocParser(),
}


def get_parser(platform: str) -> BaseParser:
    return _PARSER_MAP.get(platform, _PARSER_MAP["generic"])
