import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger(__name__)


def start_listener(settings, message_handler_callback):
    """Start Feishu WebSocket long connection listener.

    Args:
        settings: App settings with Feishu credentials.
        message_handler_callback: Function(sender_id, message_text, raw_message) to handle incoming messages.
    """

    def _on_message(data: P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            msg = event.message
            sender_id = event.sender.sender_id.open_id

            # Parse message content based on type
            msg_type = msg.message_type
            content = json.loads(msg.content)

            if msg_type == "text":
                text = content.get("text", "")
                logger.info(f"Received text from {sender_id}: {text[:100]}")
                message_handler_callback(sender_id, text, msg)

            elif msg_type == "post":
                # Rich text: extract all text and links
                texts = []
                post_content = content.get("content", content)
                # Handle zh_cn / en_us post
                if isinstance(post_content, dict):
                    for lang_content in post_content.values():
                        if isinstance(lang_content, dict):
                            for paragraph in lang_content.get("content", []):
                                for element in paragraph:
                                    if element.get("tag") == "text":
                                        texts.append(element.get("text", ""))
                                    elif element.get("tag") == "a":
                                        texts.append(element.get("href", ""))
                elif isinstance(post_content, list):
                    for paragraph in post_content:
                        for element in paragraph:
                            if element.get("tag") == "text":
                                texts.append(element.get("text", ""))
                            elif element.get("tag") == "a":
                                texts.append(element.get("href", ""))

                text = " ".join(texts)
                logger.info(f"Received post from {sender_id}: {text[:100]}")
                message_handler_callback(sender_id, text, msg)

            elif msg_type == "share_chat" or msg_type == "share_user":
                logger.info(f"Received share message, skipping: {msg_type}")

            else:
                # For other types (image, file, etc.), try to get any text
                text = content.get("text", "")
                if text:
                    message_handler_callback(sender_id, text, msg)
                else:
                    logger.info(f"Received unsupported message type: {msg_type}")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    event_handler = (
        lark.EventDispatcherHandler.builder(
            settings.feishu_encrypt_key,
            settings.feishu_verification_token,
        )
        .register_p2_im_message_receive_v1(_on_message)
        .build()
    )

    logger.info("Starting Feishu WebSocket listener...")
    client = lark.ws.Client(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    client.start()  # Blocking
