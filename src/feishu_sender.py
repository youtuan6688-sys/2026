import json
import logging
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateImageRequest,
    CreateImageRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from config.settings import Settings

logger = logging.getLogger(__name__)


class FeishuSender:
    """Send messages back to Feishu users via the IM API."""

    def __init__(self, settings: Settings):
        self.client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

    def send_text(self, receive_id: str, text: str):
        """Send a plain text message."""
        content = json.dumps({"text": text})
        self._send(receive_id, "text", content)

    def send_text_at(self, chat_id: str, text: str,
                     at_user_id: str, at_user_name: str = ""):
        """Send a text message in group chat, @mentioning a specific user.

        Args:
            chat_id: Group chat ID (starts with oc_)
            text: Message text
            at_user_id: open_id of user to @mention
            at_user_name: Display name (optional, Feishu auto-resolves)
        """
        name = at_user_name or "用户"
        at_text = f'<at user_id="{at_user_id}">{name}</at> {text}'
        content = json.dumps({"text": at_text})
        self._send(chat_id, "text", content)

    def send_card(self, open_id: str, title: str, summary: str,
                  tags: list[str], category: str, url: str):
        """Send an interactive card message showing analysis results."""
        tag_text = "  ".join(f"`{t}`" for t in tags[:8]) if tags else "无"
        card = {
            "type": "template",
            "data": {
                "template_id": "",  # No template, use raw card
                "template_variable": {}
            }
        }
        # Use raw card JSON (no template needed)
        card = {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**摘要**\n{summary}"
                },
                {
                    "tag": "markdown",
                    "content": f"**标签**: {tag_text}\n**分类**: {category}"
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "type": "primary",
                            "url": url,
                        }
                    ]
                }
            ],
            "header": {
                "title": {"tag": "plain_text", "content": f"✅ {title[:50]}"},
                "template": "green",
            }
        }
        self._send(open_id, "interactive", json.dumps(card, ensure_ascii=False))

    def upload_image(self, image_path: str) -> str | None:
        """Upload an image to Feishu and return the image_key."""
        body = CreateImageRequestBody.builder() \
            .image_type("message") \
            .image(open(image_path, "rb")) \
            .build()

        request = CreateImageRequest.builder() \
            .request_body(body) \
            .build()

        try:
            response = self.client.im.v1.image.create(request)
            if not response.success():
                logger.error(f"Failed to upload image: code={response.code}, msg={response.msg}")
                return None
            image_key = response.data.image_key
            logger.info(f"Image uploaded: {image_path} -> {image_key}")
            return image_key
        except Exception as e:
            logger.error(f"Error uploading image: {e}", exc_info=True)
            return None

    def send_image(self, open_id: str, image_path: str) -> bool:
        """Upload and send an image to a user. Returns True on success."""
        image_key = self.upload_image(image_path)
        if not image_key:
            return False
        content = json.dumps({"image_key": image_key})
        self._send(open_id, "image", content)
        return True

    def send_welcome(self, chat_id: str, name: str, open_id: str | None = None):
        """Send a welcome message to a new group member.

        Uses the 小叼毛 persona — cheeky but helpful AI buddy.

        Args:
            chat_id: Group chat ID
            name: New member's display name
            open_id: New member's open_id (for @mention)
        """
        if open_id:
            welcome = (
                f'<at user_id="{open_id}">{name}</at> '
                f'哟！又来一个勇士闯进来了 🎉\n\n'
                f'欢迎欢迎～我是群里的 AI 搭子「小叼毛」，'
                f'嘴贱但靠谱，有问题尽管 @我。\n\n'
                f'按群规矩，先来个自我介绍呗？\n'
                f'比如你是干啥的、怎么知道这个群的、对啥感兴趣～\n'
                f'随便说说就行，别害羞 😏'
            )
        else:
            welcome = (
                f'{name}！哟，又来一个勇士闯进来了 🎉\n\n'
                f'欢迎欢迎～我是群里的 AI 搭子「小叼毛」，'
                f'嘴贱但靠谱，有问题尽管 @我。\n\n'
                f'按群规矩，先来个自我介绍呗？\n'
                f'比如你是干啥的、怎么知道这个群的、对啥感兴趣～\n'
                f'随便说说就行，别害羞 😏'
            )
        content = json.dumps({"text": welcome})
        self._send(chat_id, "text", content)

    def send_error(self, open_id: str, url: str, error: str):
        """Send an error notification card."""
        card = {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**链接**: {url}\n**错误**: {error}"
                }
            ],
            "header": {
                "title": {"tag": "plain_text", "content": "❌ 处理失败"},
                "template": "red",
            }
        }
        self._send(open_id, "interactive", json.dumps(card, ensure_ascii=False))

    def _send(self, receive_id: str, msg_type: str, content: str):
        """Send a message via Feishu IM API.

        Args:
            receive_id: open_id (user) or chat_id (group, starts with "oc_")
            msg_type: message type (text, interactive, image)
            content: JSON content string
        """
        # Auto-detect receive_id type: chat_id starts with "oc_"
        id_type = "chat_id" if receive_id.startswith("oc_") else "open_id"

        body = CreateMessageRequestBody.builder() \
            .receive_id(receive_id) \
            .msg_type(msg_type) \
            .content(content) \
            .build()

        request = CreateMessageRequest.builder() \
            .receive_id_type(id_type) \
            .request_body(body) \
            .build()

        try:
            response = self.client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"Failed to send message: code={response.code}, msg={response.msg}")
            else:
                logger.info(f"Message sent to {receive_id} ({id_type}): {msg_type}")
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
