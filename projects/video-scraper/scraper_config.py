"""视频抓取分析系统 — 配置常量"""

from pathlib import Path

# ── Bitable ──────────────────────────────────────────
BITABLE_APP_TOKEN = "MnbvbQqDsaot42syrwKco3TDneg"
TASK_TABLE_ID = "tbl2vrXrzJbDHksM"
RESULT_TABLE_ID = "tblrimY09fT8JGSk"
BREAKDOWN_TABLE_ID = "tbl3ph0hmMSqZvAm"  # 逐秒拆解表

# ── Gemini ───────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_DAILY_LIMIT = 200          # 留 50 给其他用途
GEMINI_RPM = 8                    # 留 2 buffer (免费限 10)

# ── 抖音 ADB ────────────────────────────────────────
DOUYIN_PKG = "com.ss.android.ugc.aweme"
ADB = "/opt/homebrew/bin/adb"
SCRCPY = "/opt/homebrew/bin/scrcpy"
MAX_VIDEOS_PER_TASK = 20          # 单次任务上限
RECORD_BUFFER_SEC = 8             # 录屏前后 buffer
MAX_RECORD_SEC = 120              # 最长录制 2 分钟

# ── 路径 ─────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
VIDEO_DIR = DATA_DIR / "videos"
QUOTA_FILE = DATA_DIR / "gemini_quota.json"

# 创建目录
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

# ── Lark API ─────────────────────────────────────────
LARK_API_BASE = "https://open.feishu.cn/open-apis"
