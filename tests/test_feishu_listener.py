import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from src.feishu_listener import _is_duplicate, _seen_messages, _SEEN_MAX


@pytest.fixture(autouse=True)
def clear_seen():
    """Clear the seen messages cache before each test."""
    _seen_messages.clear()
    yield
    _seen_messages.clear()


class TestIsDuplicate:
    def test_first_message_not_duplicate(self):
        assert _is_duplicate("msg_001") is False

    def test_same_message_is_duplicate(self):
        _is_duplicate("msg_001")
        assert _is_duplicate("msg_001") is True

    def test_different_messages_not_duplicate(self):
        _is_duplicate("msg_001")
        assert _is_duplicate("msg_002") is False

    def test_evicts_oldest_when_full(self):
        for i in range(_SEEN_MAX + 1):
            _is_duplicate(f"msg_{i:04d}")
        # msg_0000 should have been evicted
        assert _is_duplicate("msg_0000") is False

    def test_preserves_recent_when_full(self):
        for i in range(_SEEN_MAX + 1):
            _is_duplicate(f"msg_{i:04d}")
        # The last message should still be seen as duplicate
        assert _is_duplicate(f"msg_{_SEEN_MAX:04d}") is True


class TestOnMessage:
    """Test the _on_message callback inside start_listener."""

    def _make_event_data(self, message_id="msg_001", msg_type="text",
                         content=None, sender_id="user_001"):
        """Build a mock P2ImMessageReceiveV1 event."""
        data = MagicMock()
        data.event.sender.sender_id.open_id = sender_id
        data.event.message.message_id = message_id
        data.event.message.message_type = msg_type
        data.event.message.content = json.dumps(content or {"text": "hello"})
        return data

    def _capture_on_message(self, callback):
        """Helper to capture _on_message from start_listener without blocking."""
        from src.feishu_listener import start_listener
        captured = {}

        def fake_register(fn):
            captured["on_message"] = fn
            return MagicMock(build=MagicMock())

        mock_builder = MagicMock()
        mock_builder.register_p2_im_message_receive_v1 = fake_register

        with patch("src.feishu_listener.lark.EventDispatcherHandler.builder",
                   return_value=mock_builder), \
             patch("src.feishu_listener.lark.ws.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.start.side_effect = KeyboardInterrupt
            mock_client.return_value = mock_instance

            settings = MagicMock()
            settings.feishu_encrypt_key = "key"
            settings.feishu_verification_token = "token"
            settings.feishu_app_id = "app"
            settings.feishu_app_secret = "secret"

            try:
                start_listener(settings, callback)
            except KeyboardInterrupt:
                pass

        assert "on_message" in captured
        return captured["on_message"]

    def test_text_message(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)

        on_message(self._make_event_data(
            message_id="msg_text_01", content={"text": "Hi there"},
        ))
        callback.assert_called_once()
        assert callback.call_args[0][1] == "Hi there"

    def test_duplicate_message_skipped(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        on_message(self._make_event_data(message_id="dup_01"))
        on_message(self._make_event_data(message_id="dup_01"))
        assert callback.call_count == 1  # second call skipped as duplicate

    def test_post_message_zh_cn(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        post_content = {
            "zh_cn": {
                "content": [
                    [{"tag": "text", "text": "Hello "}, {"tag": "a", "href": "https://example.com"}]
                ]
            }
        }
        data = self._make_event_data(
            message_id="post_01", msg_type="post",
            content={"content": post_content},
        )
        on_message(data)
        callback.assert_called_once()
        text = callback.call_args[0][1]
        assert "Hello" in text
        assert "https://example.com" in text

    def test_post_message_list_format(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        data = self._make_event_data(
            message_id="post_02", msg_type="post",
            content={"content": [[{"tag": "text", "text": "Plain post"}]]},
        )
        on_message(data)
        callback.assert_called_once()
        assert "Plain post" in callback.call_args[0][1]

    def test_share_message_skipped(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        data = self._make_event_data(message_id="share_01", msg_type="share_chat")
        on_message(data)
        callback.assert_not_called()

    def test_unsupported_type_with_text(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        data = self._make_event_data(
            message_id="other_01", msg_type="audio",
            content={"text": "audio transcript"},
        )
        on_message(data)
        callback.assert_called_once()
        assert callback.call_args[0][1] == "audio transcript"

    def test_unsupported_type_without_text(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        data = self._make_event_data(
            message_id="other_02", msg_type="file",
            content={"file_key": "abc"},
        )
        on_message(data)
        callback.assert_not_called()

    def test_error_handling(self):
        callback = MagicMock()
        on_message = self._capture_on_message(callback)
        # Pass a broken event that will raise an exception
        bad_data = MagicMock()
        bad_data.event.message.message_id = "err_01"
        bad_data.event.sender.sender_id.open_id = "user"
        bad_data.event.message.content = "not json"  # will fail json.loads
        bad_data.event.message.message_type = "text"

        # Should not raise
        on_message(bad_data)
