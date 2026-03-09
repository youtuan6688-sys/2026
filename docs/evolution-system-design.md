# Happycode2026 Self-Evolution System Design

## 1. Overview

A self-evolving AI assistant system that automatically detects problems, learns from mistakes, generates new capabilities, and continuously improves itself — all running autonomously on Mac Studio.

### Design Principles (from industry research)

| Source | Pattern | Our Application |
|--------|---------|----------------|
| Voyager (Minecraft AI) | Skill Library: write -> verify -> store -> reuse | Auto-generate Claude Code Skills from repeated patterns |
| Reflexion (NeurIPS 2023) | Verbal self-reflection on failure -> memory -> retry | Error -> reflection text -> learnings.md -> avoid next time |
| OpenAI Self-Evolving Cookbook | Baseline -> Evaluate -> Retrain loop | Metrics-driven evolution: track success rates, adjust |
| EvoAgentX | Modular agent ecosystem with feedback loops | Task-based architecture with evaluation |
| STOP (Self-Taught Optimizer) | Optimizer optimizes itself recursively | Evolution engine can evolve its own rules |

### Core Loop

```
SENSE -> DECIDE -> ACT -> VERIFY -> REMEMBER -> (repeat)
  |         |        |       |          |
  |         |        |       |          +-- vault/memory/, learnings.md
  |         |        |       +-- tests, health checks, metrics
  |         |        +-- task_runner.py, claude_runner.py
  |         +-- evolution_engine.py (priority, strategy)
  +-- error_tracker, health_check, cron sensors
```

---

## 2. Architecture

### Existing Infrastructure (already built)

| Component | File | Status |
|-----------|------|--------|
| Task Queue | `src/task_queue.py` | Working |
| Checkpoint | `src/checkpoint.py` | Working |
| Claude Runner | `scripts/claude_runner.py` | Working (stream-json + auto-resume) |
| Task Runner | `scripts/task_runner.py` | Working |
| Error Tracker | `src/utils/error_tracker.py` | Working |
| Health Check | `scripts/health_check.py` | Working (auto-heal) |
| Fix Task Generator | `scripts/generate_fix_tasks.py` | Working |
| Seed Tasks | `scripts/seed_evolution_tasks.py` | Working |

### New Components (to build)

| Component | File | Purpose |
|-----------|------|---------|
| Evolution Engine | `src/evolution/engine.py` | Central coordinator: sense -> decide -> act |
| Reflection Module | `src/evolution/reflection.py` | Post-task analysis, generate learnings |
| Skill Generator | `src/evolution/skill_gen.py` | Auto-create Claude Code Skills from patterns |
| Metrics Tracker | `src/evolution/metrics.py` | Track success rates, response quality, evolution progress |
| Evolution Config | `config/evolution.py` | Schedules, thresholds, strategies |
| Evolution Runner | `scripts/run_evolution.sh` | Cron entry point |

---

## 3. Component Design

### 3.1 Evolution Engine (`src/evolution/engine.py`)

The central brain. Runs on a schedule (every 2 hours + nightly deep review).

```python
class EvolutionEngine:
    """
    Coordinates the evolution loop:
    1. SENSE: Collect signals (errors, metrics, patterns)
    2. DECIDE: Prioritize what to evolve
    3. ACT: Generate and queue tasks
    4. VERIFY: Check task results
    5. REMEMBER: Update memory files
    """

    def run_cycle(self):
        signals = self.sense()        # Collect all signals
        actions = self.decide(signals) # Prioritize
        tasks = self.act(actions)      # Generate tasks
        # verify + remember happen in post-task hooks
```

**Signals collected:**
- Error patterns (ErrorTracker.get_recurring_patterns)
- Health check results
- Task completion rates
- User feedback patterns (from Feishu messages)
- Repeated operations (from session logs)
- Stale knowledge (articles not accessed in 30+ days)

**Decision strategies:**
- Priority 1: Self-repair (errors, unhealthy services)
- Priority 2: Performance (slow responses, timeouts)
- Priority 3: Capability (new skills, knowledge gaps)
- Priority 4: Quality (better prompts, better parsing)
- Priority 5: Exploration (new tools, new patterns)

### 3.2 Reflection Module (`src/evolution/reflection.py`)

Inspired by Reflexion paper. After each task completes/fails:

```python
class ReflectionModule:
    """
    Post-task reflection:
    1. Analyze task result (success/failure)
    2. Generate text reflection
    3. Store in vault/memory/learnings.md
    4. Update error patterns if failure
    """

    def reflect(self, task: Task, result: str, success: bool) -> str:
        """
        Uses Claude to generate a short reflection:
        - What was attempted?
        - What worked / didn't work?
        - What should be done differently next time?
        - Is there a reusable pattern here?
        """
```

**Key insight from Reflexion**: Verbal reflections stored as text are more useful than numeric rewards because they provide actionable context for future attempts.

### 3.3 Skill Generator (`src/evolution/skill_gen.py`)

Inspired by Voyager's skill library pattern:

```python
class SkillGenerator:
    """
    Monitors for repeating patterns and generates Claude Code Skills.

    Detection criteria:
    - Same type of task executed 3+ times
    - Similar prompts used repeatedly
    - User sends similar Feishu commands repeatedly

    Generation flow:
    1. Detect pattern
    2. Generate skill YAML/MD via Claude
    3. Write to ~/.claude/skills/ or project commands/
    4. Test the skill works
    5. Record in vault/memory/tools.md
    """
```

### 3.4 Metrics Tracker (`src/evolution/metrics.py`)

Evaluation-driven evolution (from OpenAI cookbook):

```python
class MetricsTracker:
    """
    Track evolution effectiveness:
    - task_success_rate: % of tasks completed successfully
    - avg_response_time: average Claude execution time
    - error_rate_trend: errors/day over time
    - skill_usage: how often auto-generated skills are used
    - knowledge_coverage: user questions vs knowledge base hits
    - self_heal_rate: % of auto-heals that actually fixed the issue
    """
```

Stored in `vault/metrics/evolution_metrics.json`. Monthly rollup for trend analysis.

---

## 4. Schedules & Triggers

### Cron Schedule

| Time (PST) | Task | Duration |
|------------|------|----------|
| Every 2h | Evolution cycle (light) | 5-10 min |
| 3pm (7am Beijing) | Daily briefing | 10-15 min |
| 5pm | Proactive reminder | 2 min |
| 11pm | Nightly deep review | 20-30 min |
| 11:30pm | Task queue processing | 30-60 min |

### Event Triggers

| Event | Action |
|-------|--------|
| Error occurs 3+ times | Auto-generate fix task |
| Task fails permanently | Reflection -> learnings.md |
| New skill detected in briefing | Evaluate + suggest install |
| Health check fails | Auto-heal -> report to Feishu |
| User corrects bot behavior | Extract learning, update memory |

---

## 5. Checkpoint & Resume Strategy

### For Evolution Tasks (already built, enhance)

The existing `checkpoint.py` + `claude_runner.py` handles:
- Session-based resume on timeout
- Step-by-step progress tracking
- Task queue with dependencies

### Enhancement: Evolution Checkpoint

```python
# New: vault/checkpoints/evolution_state.json
{
    "last_cycle": "2026-03-07T04:30:00",
    "cycle_number": 42,
    "pending_reflections": ["task-abc", "task-def"],
    "skill_candidates": [
        {"pattern": "url_parse", "occurrences": 5, "status": "pending_generation"}
    ],
    "metrics_snapshot": {
        "task_success_rate": 0.85,
        "error_rate_7d": 12,
        "active_skills": 3
    }
}
```

If evolution cycle is interrupted:
1. State is saved after each sub-step
2. Next cycle reads state and resumes from where it stopped
3. Stale cycles (>4h old) are reset with a summary

---

## 6. Implementation Phases

### Phase 1: Error-Driven Self-Repair (Day 1-2)
**Goal**: Close the error -> fix -> verify loop

Files to create/modify:
- `src/evolution/__init__.py` — package init
- `src/evolution/reflection.py` — post-task reflection
- `src/evolution/metrics.py` — basic metrics tracking
- `config/evolution.py` — evolution configuration
- Enhance `scripts/generate_fix_tasks.py` — add reflection after fix
- Enhance `scripts/health_check.py` — add metrics collection

Tasks:
1. Create evolution package structure
2. Build reflection module (generates text learnings from task results)
3. Build metrics tracker (success rate, error trend)
4. Wire reflection into task_runner.py (post-task hook)
5. Add evolution metrics to health check
6. Test the error -> fix -> reflect -> learn loop

### Phase 2: Evolution Engine (Day 3-4)
**Goal**: Central coordinator that runs evolution cycles

Files to create:
- `src/evolution/engine.py` — evolution engine
- `scripts/run_evolution.sh` — cron entry point
- `scripts/run_evolution.py` — Python wrapper

Tasks:
1. Build evolution engine (sense -> decide -> act)
2. Integrate with existing task queue
3. Add cron schedule (every 2 hours)
4. Build nightly deep review (comprehensive analysis)
5. Add evolution status to Feishu /status command
6. Test full evolution cycle

### Phase 3: Skill Auto-Generation (Day 5-6)
**Goal**: Automatically create reusable capabilities

Files to create:
- `src/evolution/skill_gen.py` — skill generator
- `src/evolution/pattern_detector.py` — repeated pattern detection

Tasks:
1. Build pattern detector (analyze task history for repetition)
2. Build skill generator (create Claude Code Skills from patterns)
3. Wire into evolution engine
4. Add skill effectiveness tracking
5. Test with a known repeating pattern

### Phase 4: Knowledge Evolution (Day 7+)
**Goal**: Active knowledge base management

Tasks:
1. Stale content detection and archiving
2. Knowledge gap analysis (user Q vs KB coverage)
3. Auto-ingest from RSS/bookmarks
4. Quality scoring for articles

---

## 7. File Structure

```
src/evolution/
    __init__.py
    engine.py          # Central evolution coordinator
    reflection.py      # Post-task learning extraction
    metrics.py         # Evolution metrics tracking
    skill_gen.py       # Auto skill generation
    pattern_detector.py # Repeated pattern detection

config/
    evolution.py       # Evolution schedules, thresholds

scripts/
    run_evolution.sh   # Cron entry point
    run_evolution.py   # Python wrapper

vault/
    metrics/
        evolution_metrics.json   # Daily metrics
        monthly_rollup.json      # Monthly trends
    checkpoints/
        evolution_state.json     # Evolution cycle state
    memory/
        learnings.md            # (existing) auto-updated with reflections
        tools.md                # (existing) auto-updated with new skills
```

---

## 8. Safety & Guardrails

1. **Budget cap**: Each evolution cycle max $0.50 Claude API spend
2. **Rate limit**: Max 10 tasks per evolution cycle
3. **Rollback**: All code changes via git, can revert
4. **Human override**: Feishu `/evo stop` pauses evolution, `/evo status` shows state
5. **Dry run mode**: `/evo dry-run` shows what would happen without executing
6. **Skill approval**: Auto-generated skills need user confirmation before activation (configurable)
7. **No destructive ops**: Evolution tasks can't delete files, drop data, or modify production config

---

## 9. Success Metrics

| Metric | Baseline | Target (1 month) |
|--------|----------|-------------------|
| Error self-heal rate | 0% | 60%+ |
| Task success rate | N/A | 80%+ |
| Auto-generated skills | 0 | 5+ |
| Mean time to fix | manual | < 2 hours |
| Knowledge coverage | unknown | track trend |
| Evolution cycles/day | 0 | 12 (every 2h) |

---

## 10. Dependencies & Tools Used

### Already Installed
- Claude Code CLI (task execution)
- Python 3.11 + venv
- cron + launchd (scheduling)
- Obsidian vault (knowledge storage)
- Feishu bot (notifications)
- ErrorTracker, TaskQueue, CheckpointManager

### Optional Additions (evaluate during Phase 2+)
- **Mem0** (pip install mem0ai): Structured memory layer — may replace our manual memory management
- **n8n**: Visual workflow engine — could replace cron for complex flows (evaluate cost/benefit)
- Neither is required for Phase 1-2.
