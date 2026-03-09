"""Send daily briefing report to Feishu."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.feishu_sender import FeishuSender

ADMIN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"
GROUP_CHAT_ID = "oc_4f17f731a0a3bf9489c095c26be6dedc"


def main():
    if len(sys.argv) < 2:
        print("Usage: notify_feishu.py <report_file>")
        sys.exit(1)

    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"Report not found: {report_path}")
        sys.exit(1)

    content = report_path.read_text(encoding="utf-8")
    date = report_path.stem  # e.g. 2026-03-04

    # Truncate for Feishu text message
    if len(content) > 3500:
        preview = content[:3500] + "\n\n... (full report saved locally)"
    else:
        preview = content

    sender = FeishuSender(settings)
    msg = f"Daily Briefing {date}\n\n{preview}"

    # Send to admin (private) and group chat
    sender.send_text(ADMIN_ID, msg)
    print(f"Sent to admin {ADMIN_ID}")

    sender.send_text(GROUP_CHAT_ID, msg)
    print(f"Sent to group {GROUP_CHAT_ID}")


if __name__ == "__main__":
    main()
