from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_encrypt_key: str = ""
    feishu_verification_token: str = ""

    # AI API (OpenAI-compatible: Deepseek, GPT, Kimi, etc.)
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-chat"

    # Gemini
    gemini_api_key: str = ""

    # Feishu user
    feishu_user_open_id: str = ""

    # Paths
    vault_path: str = str(PROJECT_ROOT / "vault")
    chromadb_path: str = str(PROJECT_ROOT / "data" / "chromadb")
    sqlite_path: str = str(PROJECT_ROOT / "data" / "content.db")

    # Behavior
    log_level: str = "INFO"
    max_content_length: int = 50000

    # Group chat IDs for daily reports / briefings
    group_chat_ids: list[str] = [
        "oc_4f17f731a0a3bf9489c095c26be6dedc",
        "oc_d7120356187aed1e651863428e55ab47",
        "oc_d42807f92f606dc0b448f16c6c42fece",  # 爆款视频拆解实验室
    ]

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()

# Shared constants
CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"
