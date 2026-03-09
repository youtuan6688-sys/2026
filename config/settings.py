from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_encrypt_key: str = ""
    feishu_verification_token: str = ""

    # Claude API
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    # Paths
    vault_path: str = str(PROJECT_ROOT / "vault")
    chromadb_path: str = str(PROJECT_ROOT / "data" / "chromadb")
    sqlite_path: str = str(PROJECT_ROOT / "data" / "content.db")

    # Behavior
    log_level: str = "INFO"
    max_content_length: int = 50000

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
