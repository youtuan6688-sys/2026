import json
import logging
from collections import OrderedDict
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, P2ImChatMemberUserAddedV1

logger = logging.getLogger(__name__)

# Persistent LRU cache for deduplicating messages (survives restarts)
_SEEN_FILE = Path("/Users/tuanyou/Happycode2026/data/seen_messages.json")
_SEEN_MAX = 200
_seen_messages: OrderedDict[str, bool] = OrderedDict()


def _load_seen_cache():
    """Load dedup cache from disk on startup."""
    global _seen_messages
    try:
        if _SEEN_FILE.exists():
            ids = json.loads(_SEEN_FILE.read_text(encoding="utf-8"))
            # Only keep last _SEEN_MAX entries
            for mid in ids[-_SEEN_MAX:]:
                _seen_messages[mid] = True
            logger.info(f"Loaded {len(_seen_messages)} message IDs from dedup cache")
    except Exception as e:
        logger.warning(f"Failed to load dedup cache: {e}")


def _save_seen_cache():
    """Persist dedup cache to disk."""
    try:
        _SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SEEN_FILE.write_text(
            json.dumps(list(_seen_messages.keys()), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save dedup cache: {e}")


def _is_duplicate(message_id: str) -> bool:
    """Check if we've already processed this message ID."""
    if message_id in _seen_messages:
        return True
    _seen_messages[message_id] = True
    if len(_seen_messages) > _SEEN_MAX:
        _seen_messages.popitem(last=False)
    _save_seen_cache()
    return False


# Load cache on module import
_load_seen_cache()


def start_listener(settings, message_handler_callback, feishu_sender=None):
    """Start Feishu WebSocket long connection listener.

    Args:
        settings: App settings with Feishu credentials.
        message_handler_callback: Function(sender_id, message_text, raw_message) to handle incoming messages.
        feishu_sender: Optional FeishuSender instance for sending welcome messages.
    """

    def _on_member_added(data: P2ImChatMemberUserAddedV1) -> None:
        """Handle new members joining a group chat."""
        try:
            event = data.event
            chat_id = event.chat_id
            users = event.users or []

            if not feishu_sender:
                logger.warning("No feishu_sender configured, skipping welcome message")
                return

            for user in users:
                name = user.name or "新朋友"
                open_id = user.user_id.open_id if user.user_id else None

                logger.info(f"New member joined chat {chat_id}: {name} ({open_id})")

                feishu_sender.send_welcome(chat_id, name, open_id)

        except Exception as e:
            logger.error(f"Error handling member added event: {e}", exc_info=True)

    def _on_message(data: P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            msg = event.message
            sender_id = event.sender.sender_id.open_id
            chat_id = msg.chat_id
            chat_type = msg.chat_type  # "p2p" or "group"

            # Deduplicate: skip if we've already processed this message
            if _is_duplicate(msg.message_id):
                logger.debug(f"Duplicate message ignored: {msg.message_id}")
                return

            # Determine reply target: group chat → chat_id, private → sender open_id
            reply_id = chat_id if chat_type == "group" else sender_id

            # Extract @mention user IDs to clean from text
            mentions = msg.mentions or []
            mention_keys = {m.key for m in mentions if hasattr(m, "key") and m.key}

            # Group chat: only respond when bot is @mentioned
            if chat_type == "group" and not mentions:
                logger.debug(f"Group message without @mention, skipping: {msg.message_id}")
                return

            # Parse message content based on type
            msg_type = msg.message_type
            content = json.loads(msg.content)

            if msg_type == "text":
                text = content.get("text", "")
                # Remove @mention placeholders (e.g., @_user_1)
                for key in mention_keys:
                    text = text.replace(key, "").strip()
                logger.info(f"Received text [{chat_type}] from {sender_id}: {text[:100]}")
                message_handler_callback(reply_id, text, msg, chat_type=chat_type, sender_open_id=sender_id)

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
                # Remove @mention placeholders
                for key in mention_keys:
                    text = text.replace(key, "").strip()
                logger.info(f"Received post [{chat_type}] from {sender_id}: {text[:100]}")
                message_handler_callback(reply_id, text, msg, chat_type=chat_type, sender_open_id=sender_id)

            elif msg_type == "share_chat" or msg_type == "share_user":
                logger.info(f"Received share message, skipping: {msg_type}")

            else:
                # For other types (image, file, etc.), try to get any text
                text = content.get("text", "")
                if text:
                    message_handler_callback(reply_id, text, msg, chat_type=chat_type, sender_open_id=sender_id)
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
        .register_p2_im_chat_member_user_added_v1(_on_member_added)
        .build()
    )

    logger.info("Starting Feishu WebSocket listener...")
    client = lark.ws.Client(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    client.start()

    # client.start() may return immediately if it uses daemon threads.
    # Keep the main thread alive.
    import time
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Listener stopped by user.")
