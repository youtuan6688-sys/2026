from pathlib import Path

from config.settings import Settings, PROJECT_ROOT


class TestSettings:
    def test_defaults(self):
        s = Settings(
            feishu_app_id="id", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        assert s.log_level == "INFO"
        assert s.max_content_length == 50000
        assert s.ai_model == "deepseek-chat"

    def test_custom_values(self):
        s = Settings(
            feishu_app_id="id", feishu_app_secret="secret",
            feishu_encrypt_key="enc", feishu_verification_token="tok",
            log_level="DEBUG", max_content_length=10000,
        )
        assert s.log_level == "DEBUG"
        assert s.max_content_length == 10000

    def test_project_root(self):
        assert PROJECT_ROOT.is_dir()
        assert (PROJECT_ROOT / "config").is_dir()

    def test_paths_are_strings(self):
        s = Settings(
            feishu_app_id="id", feishu_app_secret="secret",
            feishu_encrypt_key="", feishu_verification_token="",
        )
        assert isinstance(s.vault_path, str)
        assert isinstance(s.chromadb_path, str)
        assert isinstance(s.sqlite_path, str)
