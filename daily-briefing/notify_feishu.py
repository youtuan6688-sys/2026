"""Send daily briefing report to Feishu."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.feishu_sender import FeishuSender

RECIPIENT = "ou_4a18a2e35a5b04262a24f41731046d15"


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
    sender.send_text(RECIPIENT, f"Daily Briefing {date}\n\n{preview}")
    print(f"Sent to {RECIPIENT}")


if __name__ == "__main__":
    main()
