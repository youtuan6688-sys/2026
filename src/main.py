import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.feishu_listener import start_listener
from src.feishu_sender import FeishuSender
from src.message_router import MessageRouter
from src.ai.analyzer import AIAnalyzer
from src.storage.vector_store import VectorStore
from src.storage.content_index import ContentIndex
from src.storage.obsidian_writer import ObsidianWriter
from src.utils.error_tracker import ErrorTracker


def main():
    # Setup logging
    log_file = Path(settings.vault_path).parent / "logs" / "service.log"
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
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
    sender = FeishuSender(settings)
    error_tracker = ErrorTracker()
    router = MessageRouter(ai_analyzer, writer, content_index, sender, vector_store, error_tracker)

    # Pre-warm embedding model at startup (avoid 8s delay on first message)
    try:
        from src.ai.embeddings import get_embedding_model
        get_embedding_model()
    except Exception as e:
        logger.warning(f"Embedding model pre-warm failed (will retry on first query): {e}")

    # Auto-reindex if article count changed since last index
    try:
        vault = Path(settings.vault_path)
        article_count = sum(1 for d in ("articles", "social", "docs")
                           if (vault / d).exists()
                           for _ in (vault / d).glob("*.md"))
        indexed_count = vector_store.collection.count()
        if article_count > indexed_count:
            logger.info(f"New articles detected ({article_count} files vs {indexed_count} indexed), reindexing...")
            import subprocess
            subprocess.Popen(
                [sys.executable, "scripts/reindex_vault.py"],
                cwd=str(vault.parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            logger.info(f"Vector store up to date ({indexed_count} docs, {article_count} files)")
    except Exception as e:
        logger.warning(f"Auto-reindex check failed: {e}")

    # Recover orphaned long tasks from previous crash (delayed notification)
    import threading

    def _notify_recovered_task():
        import time
        time.sleep(5)  # Wait for listener to be ready
        try:
            from src.long_task import LongTaskManager
            ltm = LongTaskManager()
            orphan = ltm.recover_orphaned()
            if orphan:
                sender.send_text(
                    orphan.sender_id,
                    f"⚠️ 上次中断的任务已恢复\n"
                    f"任务: {orphan.original_prompt[:100]}\n"
                    f"已完成 {orphan.steps_completed} 步\n"
                    f"发送「继续」恢复执行",
                )
                logger.info(f"Notified user of interrupted task: {orphan.task_id}")
        except Exception as e:
            logger.warning(f"Long task recovery notification failed: {e}")

    threading.Thread(target=_notify_recovered_task, daemon=True).start()

    logger.info("All components initialized. Starting Feishu listener...")

    # Start Feishu WebSocket listener (blocking)
    start_listener(settings, router.handle_message, feishu_sender=sender)


if __name__ == "__main__":
    main()
