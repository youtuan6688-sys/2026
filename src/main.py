import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.feishu_listener import start_listener
from src.message_router import MessageRouter
from src.ai.analyzer import AIAnalyzer
from src.storage.vector_store import VectorStore
from src.storage.content_index import ContentIndex
from src.storage.obsidian_writer import ObsidianWriter


def main():
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                Path(settings.vault_path).parent / "logs" / "service.log",
                encoding="utf-8",
            ),
        ],
    )
    logger = logging.getLogger(__name__)

    # Ensure data directories exist
    Path(settings.chromadb_path).mkdir(parents=True, exist_ok=True)
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.vault_path).mkdir(parents=True, exist_ok=True)

    logger.info("=== HappyCode Knowledge System Starting ===")
    logger.info(f"Vault path: {settings.vault_path}")

    # Initialize components
    vector_store = VectorStore(settings.chromadb_path)
    content_index = ContentIndex(settings.sqlite_path)
    ai_analyzer = AIAnalyzer(settings, vector_store)
    writer = ObsidianWriter(settings, vector_store, content_index)
    router = MessageRouter(ai_analyzer, writer, content_index)

    logger.info("All components initialized. Starting Feishu listener...")

    # Start Feishu WebSocket listener (blocking)
    start_listener(settings, router.handle_message)


if __name__ == "__main__":
    main()
