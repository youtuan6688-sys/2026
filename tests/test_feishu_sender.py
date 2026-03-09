import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestFeishuSender:
    @patch("src.feishu_sender.lark")
    def test_send_text(self, mock_lark):
        mock_client = MagicMock()
        mock_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = mock_client

        mock_response = MagicMock()
        mock_response.success.return_value = True
        mock_client.im.v1.message.create.return_value = mock_response

        from src.feishu_sender import FeishuSender
        from config.settings import Settings
        settings = Settings(
            feishu_app_id="test", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        sender = FeishuSender(settings)
        sender.client = mock_client

        sender.send_text("open_id_123", "Hello")
        mock_client.im.v1.message.create.assert_called_once()

    @patch("src.feishu_sender.lark")
    def test_send_card(self, mock_lark):
        mock_client = MagicMock()
        mock_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = mock_client

        mock_response = MagicMock()
        mock_response.success.return_value = True
        mock_client.im.v1.message.create.return_value = mock_response

        from src.feishu_sender import FeishuSender
        from config.settings import Settings
        settings = Settings(
            feishu_app_id="test", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        sender = FeishuSender(settings)
        sender.client = mock_client

        sender.send_card(
            open_id="open_id_123",
            title="Test Title",
            summary="Test summary",
            tags=["tag1", "tag2"],
            category="tech",
            url="https://example.com",
        )
        mock_client.im.v1.message.create.assert_called_once()

    @patch("src.feishu_sender.lark")
    def test_send_error(self, mock_lark):
        mock_client = MagicMock()
        mock_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = mock_client

        mock_response = MagicMock()
        mock_response.success.return_value = True
        mock_client.im.v1.message.create.return_value = mock_response

        from src.feishu_sender import FeishuSender
        from config.settings import Settings
        settings = Settings(
            feishu_app_id="test", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        sender = FeishuSender(settings)
        sender.client = mock_client

        sender.send_error("open_id_123", "https://fail.com", "parse error")
        mock_client.im.v1.message.create.assert_called_once()

    @patch("src.feishu_sender.lark")
    def test_send_failure_logs_error(self, mock_lark):
        mock_client = MagicMock()
        mock_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = mock_client

        mock_response = MagicMock()
        mock_response.success.return_value = False
        mock_response.code = 400
        mock_response.msg = "bad request"
        mock_client.im.v1.message.create.return_value = mock_response

        from src.feishu_sender import FeishuSender
        from config.settings import Settings
        settings = Settings(
            feishu_app_id="test", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        sender = FeishuSender(settings)
        sender.client = mock_client

        # Should not raise, just log
        sender.send_text("open_id_123", "Hello")
