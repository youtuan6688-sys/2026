# Happycode2026 Project Contract

## Build & Run
- Python 3.11, venv at `.venv/`
- Activate: `source .venv/bin/activate`
- Run bot: `python src/main.py`
- Run briefing: `bash daily-briefing/run_briefing.sh`
- Config: `.env` (secrets) + `config/settings.py` (app config)

## Architecture Boundaries
- `src/` — Bot core (message routing, Feishu listener/sender, Claude runner)
- `src/main.py` → `feishu_listener.py` → `message_router.py` → `router_claude.py`
- `vault/` — Obsidian knowledge base (articles/, social/, memory/)
- `daily-briefing/` — Cron-driven daily briefing system
- `projects/` — Sub-projects (video-scraper, etc.)
- `scripts/` — Deployment and utility scripts
- Do NOT put business logic in feishu_listener.py (it only handles webhook)
- Do NOT import feishu_sender directly from router — use message_router as mediator

## Coding Conventions
- Language: Python 3.11, type hints encouraged
- Use `logging` module, never `print()` for production code
- Config via `os.getenv()` or `config/settings.py`, never hardcode
- Chinese comments OK, docstrings in English or Chinese
- Immutable patterns preferred: return new dicts, don't mutate in-place

## Safety Rails

### NEVER
- Commit `.env` or any file containing API keys/tokens
- Run `rm -rf` on vault/ or src/ directories
- Push to main without testing bot startup
- Modify feishu webhook verification logic without explicit approval
- Send test messages to production Feishu groups without confirmation

### ALWAYS
- Validate Feishu webhook signatures before processing
- Handle API errors with try/except and logging
- Test bot startup (`python src/main.py`) after code changes
- Back up vault/memory/ before bulk modifications

## Verification
- Bot changes: `python src/main.py` starts without errors
- Router changes: verify message classification with test messages
- Knowledge base: check vault/ file created with correct frontmatter
- Briefing: `bash daily-briefing/run_briefing.sh` completes successfully

## Compact Instructions

When compressing context, preserve in priority order:
1. Architecture decisions and module boundaries (NEVER summarize away)
2. Modified files and their key changes
3. Current task status (what's done, what's pending)
4. Feishu bot state (PID, running/stopped, recent errors)
5. Open TODOs and rollback notes
6. Tool outputs can be deleted — keep pass/fail status only
