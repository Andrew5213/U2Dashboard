# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bidirectional middleware API synchronizing **ClickUp** with **AltoQI Visus Workflow** (powered by Airbox). Built with FastAPI + async SQLAlchemy.

**Business domain:** The system is built for **U2 Broadcast Angola** to track the installation of radio studios and FM sites across Angolan provinces. In the data model, *Folder = Province*, *List = Module* (Studio or FM Site), *Task = Discipline* (Civil Works, Electrical, etc.), and *Subtask = Activity*. The AI assistant persona is "Assistente U2, gestor de projetos da U2 Broadcast Angola".

The AltoQI Visus Workflow platform exposes the **Airbox public API** at `https://workflow-api.altoqivisus.com.br`. Spec: `https://app.swaggerhub.com/apis/Airbox/AirboxAPI/1.1.0`.

## Commands

```bash
# Setup
pip install -r requirements.txt
pip install mypy pytest-env  # dev tools not in requirements.txt
# Create .env manually with the variables listed in the Key Configuration table below

# Run (dev)
uvicorn src.main:app --reload --port 8000

# Run (prod)
uvicorn src.main:app --host 0.0.0.0 --port 8000

# Tests
pytest                                                                          # all tests
pytest tests/unit/test_mapper.py                                               # single file
pytest tests/unit/test_mapper.py::TestAirboxTaskToClickUp::test_maps_name     # single test

# Type checking (config.py errors are suppressed in mypy.ini — expected)
mypy src/

# One-off initial sync (ClickUp → Airbox)
python scripts/initial_sync.py --space-id <CLICKUP_SPACE_ID>

# Populate/force-refresh the ClickUp cache manually (useful on first run)
python scripts/init_cache.py --space-id <CLICKUP_SPACE_ID>

# Register ClickUp webhook pointing at this server
python scripts/register_webhook.py --space-id <SPACE_ID> --url https://your-domain.com/webhooks/clickup
```

## Architecture

```
src/
├── main.py              # FastAPI app + lifespan (init_db, start polling, start cache worker, start email worker)
├── static/              # Served at /static (CSS, JS for dashboard UI)
├── img/                 # Served at /img (images for dashboard UI)
├── templates/
│   ├── index.html         # Jinja2 dashboard UI (served at GET / — desktop)
│   ├── index_mobile.html  # Mobile variant — selected by UA detection in main.py
│   ├── chat.html          # AI assistant page (served at GET /assistente — desktop)
│   ├── chat_mobile.html   # Mobile variant
│   ├── rdo.html           # RDO form (served at GET /rdo)
│   └── progress_civil.html # Civil progress view (served at GET /progresso-civil)
├── core/
│   ├── config.py        # Settings via pydantic-settings (reads .env)
│   ├── database.py      # Async SQLAlchemy engine, Base, get_db, init_db
│   └── logging.py       # Loguru setup
├── models/
│   ├── schemas.py           # Pydantic DTOs: AirboxTask, AirboxAgreement, ClickUpTask, SyncResult
│   ├── sync_map.py          # SQLAlchemy ORM: TaskSyncMap, AgreementSyncMap, SyncLog
│   ├── cache_models.py      # SQLAlchemy ORM: ClickUpSpaceCache, FolderCache, ListCache, TaskCache, UserCache, CacheRefreshLog, DisciplineWeight
│   ├── dashboard_schemas.py # Pydantic response schemas for dashboard API
│   ├── chat_schemas.py      # Pydantic DTOs: ChatRequest, ChatResponse, ChartPayload
│   ├── civil_models.py      # ORM: CivilProject, CivilSite + 9 child tables (report, resource, activity, material, occurrence, quality_check, photo, next_day_plan, signature)
│   └── progress_models.py   # ORM: CivilProgressProfile, CivilProgressCategory, CivilProgressActivityDef, CivilSiteActivityQty, CivilProgressMeasurement
├── repositories/
│   ├── sync_repository.py   # DB access for sync tables
│   ├── cache_repository.py  # DB access for cache tables (upsert_space/folder/list/task/user, weighted progress, discipline weights)
│   └── civil_repository.py  # DB access for all civil + progress tables (shared by civil.py, progress_civil.py, civil_service.py)
├── services/
│   ├── airbox_client.py     # httpx async client for Airbox API
│   ├── clickup_client.py    # httpx async client for ClickUp REST API v2
│   ├── mapper.py            # Field mapping ClickUp ↔ Airbox + stage/status constants
│   ├── sync_service.py      # Orchestrates sync logic ClickUp → Airbox
│   ├── cache_service.py     # Refreshes local SQLite cache from ClickUp API
│   ├── event_broadcaster.py # In-process asyncio pub/sub for SSE events
│   ├── dashboard_service.py # Reads from cache tables to serve dashboard API
│   ├── report_service.py    # Generates PDF reports via fpdf2 (ReportService + ProvinceReportService + PeriodicReportService)
│   ├── report_strings.py    # Bilingual string dictionaries for PDF text (PT/EN), keyed by get_strings(lang)
│   ├── translation.py       # Static PT→EN dict for ClickUp field names (disciplines, activities, statuses) via translate()
│   ├── weights_config.py    # EVM weight constants + compute_province_progress / compute_list_progress / build_province_evolution
│   ├── chat_service.py      # Agentic loop: Claude Haiku + tool use → ChatResponse (with optional ChartPayload)
│   ├── chat_tools.py        # TOOL_DEFINITIONS (9 tools) + dispatch_tool() routing to DashboardService/CacheRepository
│   ├── email_service.py     # EmailService: builds MIME email, attaches PT+EN PDFs, sends via SMTP (asyncio.to_thread)
│   ├── civil_service.py     # CivilService: orchestrates RDO creation (nested children, sequential numbering, auto-fill measurements)
│   ├── progress_service.py  # ProgressService + pure EVM functions (pct, activity_contribution, global_progress)
│   └── rdo_pdf_service.py   # generate_rdo_pdf(report, site_name) → bytes — fpdf2-based RDO PDF
├── api/
│   ├── health.py            # GET /health
│   ├── sync.py              # POST /sync/trigger, GET /sync/status|logs, GET+POST /sync/mappings/agreements
│   ├── webhooks.py          # POST /webhooks/clickup — verifies HMAC, syncs to Airbox, updates cache + SSE
│   ├── dashboard.py         # GET /dashboard/overview|folders|folder/{id}|list/{id}|task/{id}|assignees|upcoming|evolution
│   │                        #   GET /dashboard/gantt/{list_id}|gantt/folder/{id}|gantt/task/{id}
│   │                        #   POST /dashboard/refresh
│   ├── dashboard_stream.py  # GET /dashboard/stream (Server-Sent Events)
│   ├── reports.py           # GET /reports/pdf, /reports/pdf/provincia, /reports/pdf/daily, /reports/pdf/weekly, /reports/folders
│   │                        #   POST /reports/email/send — manual trigger for weekly email (fires in background)
│   ├── disciplines.py       # GET/POST/DELETE /disciplines/folder/{folder_id}
│   ├── chat.py              # POST /chat, GET /chat/status
│   ├── civil.py             # /civil/* — Projects, Sites, DailyReports (RDO), photo upload
│   └── progress_civil.py    # /civil/progress/* — Profiles, Categories, ActivityDefs, Quantities, Measurements, progress summaries
└── workers/
    ├── polling_worker.py    # APScheduler: ClickUp → Airbox sync on interval
    ├── cache_worker.py      # APScheduler: refreshes local ClickUp cache on interval
    └── email_worker.py      # APScheduler: sends weekly PDF report via email on configured weekday/hour UTC
```

## Sync Flows

**ClickUp → Airbox** (primary direction, two triggers):
1. Polling worker (APScheduler) — fires every `POLLING_INTERVAL_SECONDS` if `CLICKUP_DEFAULT_SPACE_ID` is set
2. Manual trigger — `POST /sync/trigger?space_id=<id>`

Flow: `ClickUpClient` reads all lists (folderless + inside folders) in the space → for each list, resolves the corresponding Airbox `Agreement` by name (case-insensitive match via `AgreementSyncMap`) → `ClickUpClient.get_tasks()` fetches tasks → for each task without an existing `TaskSyncMap`, calls `AirboxClient.create_task()`. Already-synced tasks are skipped (idempotent).

**ClickUp → Airbox via webhook**:
`POST /webhooks/clickup` → verify HMAC-SHA256 signature → dispatch by event type:
- `taskCreated` → fetches full task from ClickUp, resolves agreement, creates task in Airbox via `POST /tasks`
- `taskUpdated`, `taskStatusUpdated`, `taskAssigneeUpdated`, `taskDueDateUpdated` → logged but not propagated (**Limitation:** Airbox public API has no `PATCH /tasks` endpoint)

After each handled webhook event, the cache is updated and an SSE broadcast fires (fire-and-forget — does not block the response).

## Dashboard & Cache Layer

The app maintains a local SQLite cache of the ClickUp space structure to serve the dashboard UI without hitting the ClickUp API on every page load.

**Cache refresh sources:**
1. `cache_worker.py` — APScheduler job, runs every `CACHE_REFRESH_INTERVAL_SECONDS` (default 300s). Enabled when both `DASHBOARD_ENABLED=true` and `CLICKUP_DEFAULT_SPACE_ID` is set. On first run (`CACHE_REFRESH_ON_STARTUP=true`) fires immediately.
2. `POST /dashboard/refresh` — triggers a full cache refresh in background.
3. Webhook events — `CacheService.apply_webhook_event()` patches individual tasks in the cache, then broadcasts via SSE.

**SSE stream**: `GET /dashboard/stream` — clients receive `update` events (with `type`, `task_id`, `list_id`) whenever a webhook updates a task. Sends `ping` keepalives every `SSE_KEEPALIVE_SECONDS` (default 15s).

**Dashboard UI**: served at `GET /` via `src/templates/index.html` (or `index_mobile.html`). The frontend calls `/dashboard/*` REST endpoints and connects to `/dashboard/stream` for live updates.

**Mobile template selection** (`main.py`): `_is_mobile()` checks the `?view=` query param first (`desktop` or `mobile` to force), then falls back to user-agent sniffing for `mobile/android/iphone/ipad/ipod`. Both `GET /` and `GET /assistente` follow this pattern.

**Static assets**: `src/static/echarts.min.js` is a locally bundled copy of Apache ECharts — it is not fetched from a CDN. When upgrading ECharts, replace this file manually.

## PDF Reports

Four report types, all generated on-demand using `fpdf2` (Latin-1 fonts — use `_s()` helper to sanitize em-dashes, curly quotes, etc.). Every PDF endpoint accepts `?lang=pt|en` (default `pt`) and `?inline=true` to stream in-browser.

- **`GET /reports/pdf`** — executive report for the full space (cover + summary + project health + overdue + upcoming + team performance). Uses `ReportService`.
- **`GET /reports/pdf/provincia?folder_id=<id>`** — detailed report for a single folder/province (cover + summary + per-list detail with task-level breakdown). Uses `ProvinceReportService`. Incorporates EVM weighted progress when discipline weights are configured.
- **`GET /reports/pdf/daily`** — daily updates report (tasks created/completed yesterday and today). Uses `PeriodicReportService`.
- **`GET /reports/pdf/weekly`** — weekly updates report (last 7 days). Uses `PeriodicReportService`.
- **`GET /reports/folders`** — lists folders available for province reports (reads from cache).

Bilingual support: `report_strings.py` holds all UI strings keyed by `get_strings(lang)`. `translation.py` maps normalized Portuguese field names → English equivalents via `translate()` / `translate_task_row()`.

## AI Agent (Chat)

The assistant lives at `GET /assistente` (HTML page) and is backed by `POST /chat`.

**Agentic loop** (`ChatService.ask`):
1. User message arrives → `_detect_forced_tool()` checks for temporal/status keywords and may force a specific tool on iteration 1 via `tool_choice: {type: "tool", name: ...}`.
2. Claude Haiku is called with `TOOL_DEFINITIONS` (9 tools, all read-only against the SQLite cache).
3. On `stop_reason == "tool_use"`, each `tool_use` block is dispatched by `dispatch_tool()` in `chat_tools.py`, which calls `DashboardService` or `CacheRepository` and returns `(text_for_claude, raw_data_for_chart)`.
4. Loop continues up to `CHAT_MAX_ITERATIONS` (default 5). On `end_turn`, `_build_chart()` picks the highest-priority tool result and constructs a `ChartPayload` (bar, pie, line, table, or kpi).

**Tools available to the agent** (defined in `chat_tools.py::TOOL_DEFINITIONS`):

| Tool | Purpose |
|---|---|
| `get_recent_changes` | Tasks created/completed/active in a time window (today/yesterday/week/month) |
| `list_tasks_by_status` | All tasks grouped by current status, with optional status filter |
| `get_overview_kpis` | Space-level KPIs (totals, completion rate, status distribution) |
| `list_folders` | All provinces with task counts and completion rates |
| `get_folder_progress` | EVM-weighted progress breakdown for a single province |
| `list_overdue_tasks` | Overdue tasks, optionally filtered by province |
| `list_upcoming_tasks` | Tasks due within N future days |
| `get_assignee_stats` | Open/completed/overdue counts per team member |
| `get_evolution_curve` | Historical weighted-progress series for all provinces |

**Keyword forcing** (`_detect_forced_tool`): if the user message contains temporal keywords ("hoje", "semana", "mudou", etc.) the loop forces `get_recent_changes` on the first call; status keywords ("fazendo", "revisão", "aprovação", etc.) force `list_tasks_by_status`. This is a deterministic override on top of Claude's own routing.

**Province name resolution** (`_resolve_folder`): exact match → single partial match → list of candidates returned as error for Claude to handle.

**Chart priority**: when multiple tools fire in one turn, `_TOOL_PRIORITY` picks which one drives the chart (e.g., `get_folder_progress` wins over `list_folders`).

## Weighted Progress (EVM)

The province report and `/disciplines` API implement a two-level Earned Value Method:

```
Folder (Province)
  └─ List (Module: Studio / FM Site)           ← equal weight per list within folder
       └─ Task = Discipline (e.g. Civil Works) ← weights from TASK_WEIGHTS in weights_config.py
            └─ Subtask = Activity (e.g. Walls) ← weights from SUBTASK_WEIGHTS in weights_config.py
```

**How progress is calculated** (`weights_config.py`):
- `compute_task_progress(task, subtasks)` — if parent task is done → 1.0; else weighted sum of subtask completion using `SUBTASK_WEIGHTS`. Unknown subtask names fall back to weight 1.0 (equal).
- `compute_list_progress(tasks)` — weighted sum across disciplines using `TASK_WEIGHTS`. Unknown task names fall back to weight 1.0.
- `compute_province_progress(lists_data)` — simple average across lists (each list has equal weight within the folder).

**`TASK_WEIGHTS`** — relative weights for discipline names (Portuguese and English variants for Studio and FM Site project types). These are normalized at calculation time so they don't need to sum to any specific value.

**`SUBTASK_WEIGHTS`** — relative weights for activity names, keyed by discipline name. Both keys are normalized (no accents, lowercase, alphanumeric only) via `_norm()`.

**Overriding weights via API**: `POST /disciplines/folder/{folder_id}` saves per-list weights (0.0–1.0, must sum to 1.0) to the `discipline_weights` DB table. `GET /disciplines/folder/{folder_id}` returns current weighted progress. When DB weights exist for a folder's lists, `get_weighted_progress()` uses them instead of the equal-weight fallback.

**Evolution curve** (`build_province_evolution`): reconstructs a temporal weighted-progress series from `date_closed` of each completed task. Used by `GET /dashboard/evolution` → `DashboardService.get_evolution_data()`. Each point is `{date: ISO, progress: float}` representing cumulative weighted progress at that moment. The series always starts at 0.0 (first task creation date) and ends with today's current value.

## Civil Works Module (RDO)

The civil works module is independent of the ClickUp↔Airbox sync and manages construction site daily reports (RDO — *Relatório Diário de Obra*).

**Domain hierarchy:**
```
CivilProject
  └─ CivilSite (linked to a CivilProgressProfile for EVM tracking)
       └─ CivilDailyReport (one per site per date — enforced by unique constraint)
            ├─ CivilResource      (personnel by discipline)
            ├─ CivilActivity      (work executed; optional link to ActivityDef feeds measurements)
            ├─ CivilMaterial      (received/applied; balance computed in response)
            ├─ CivilOccurrence    (incidents, blockers, risks)
            ├─ CivilQualityCheck  (5 fixed items from CIVIL_QUALITY_CHECKS — auto-created)
            ├─ CivilPhoto         (files stored on disk, path in DB)
            ├─ CivilNextDayPlan   (planned activities for the following day)
            └─ CivilSignature     (3 fixed roles from CIVIL_SIGNATURE_ROLES — auto-created)
```

**Auto-behaviors in `CivilService.create_report`:**
- `report_number` is assigned sequentially per site (max + 1)
- Missing `quality_check` rows are auto-created for all 5 fixed `check_type` values
- Missing `signature` rows are auto-created for all 3 fixed `role` values
- Activities with `activity_def_id` + `qty_day` trigger `_auto_fill_measurements()` which upserts a `CivilProgressMeasurement` (cumulative: yesterday's measurement + today's qty_day, wins only if greater than existing)

**Photo upload:** `POST /civil/reports/{id}/photos` — multipart, max 20 MB, stored at `settings.civil_uploads_dir/<report_id>_<uuid>.<ext>`, served at `/uploads/<stored_name>`.

**PDF export:** `generate_rdo_pdf(report_dict, site_name)` in `rdo_pdf_service.py`. Same `_s()` Latin-1 sanitizer and fpdf2 pattern as `report_service.py`.

## Civil Progress (EVM for Construction)

Independent EVM system for civil works — separate from the ClickUp-based EVM in `weights_config.py`.

**Hierarchy:**
```
CivilProgressProfile  (e.g. "Site TX com torre", "Luanda")
  └─ CivilProgressCategory (weight, sort_order)
       └─ CivilProgressActivityDef (unit, sort_order)

CivilSite.profile_id → CivilProgressProfile
CivilSiteActivityQty  (site_id, activity_def_id, total_qty — planned quantity)
CivilProgressMeasurement (site_id, activity_def_id, date, qty_yesterday, qty_today)
```

**Calculation (`progress_service.py`):**
- `pct(qty, total)` → `min(qty / total, 1.0)` — clamped percentage
- `activity_contribution = category_weight × pct`
- `site_progress = Σ contributions` across all activities of the site's profile
- `global_progress = mean(site_progress)` for sites that have measurements on the given date

**Key endpoint:** `GET /civil/progress/site/{site_id}?date=YYYY-MM-DD` returns `SiteProgressResult` (dataclass serialized via `dataclasses.asdict`). `GET /civil/progress/summary` returns `GlobalProgressResult`.

**FK note:** `CivilSite.profile_id` references `civil_progress_profile`. Both `civil_models` and `progress_models` **must be imported** in `main.py` before `init_db()` runs — the current import order in `main.py` handles this correctly. Reordering these imports will cause FK errors at table creation.

## Agreement ↔ List Matching

Lists and agreements are matched **by name** (case-insensitive). If names don't match:
1. Check existing mappings: `GET /sync/mappings/agreements`
2. Create manual mapping: `POST /sync/mappings/agreements` (body: `clickup_list_id`, `clickup_list_name`, `airbox_agreement_id`)

## Database

SQLite (`sync.db`), both locally and in production. No Postgres — schema is auto-created at startup via `Base.metadata.create_all`, which only creates missing tables, it never alters existing ones (no migrations); `alembic` is listed in `requirements.txt` but is not used. **If you change ORM models, delete `sync.db` (or `dev.db` locally) to recreate.** A schema change to an existing table (new column, changed type) in production requires either deleting the file (losing data) or a manual `ALTER TABLE`, since there's no migration tooling.

**Production persistence (Railway) requires a mounted Volume** — Railway's container filesystem is wiped on every redeploy. Without a Volume, `sync.db` (and therefore every RDO, project, site, and ClickUp cache row) is lost on the next deploy. Mount a Volume at `/data` on the web service and set `DATABASE_URL=sqlite+aiosqlite:////data/sync.db` (four slashes: `sqlite+aiosqlite://` + absolute path `/data/sync.db`). Also point `CIVIL_UPLOADS_DIR=/data/uploads` at the same volume so RDO photo files survive redeploys too — see `.env.example`.

Upserts (`INSERT ... ON CONFLICT`) use `sqlalchemy.dialects.sqlite.insert` directly in `cache_repository.py` and `civil_repository.py` — this only works against SQLite; if the backend ever changes, these call sites need to change too.

The `import src.models.cache_models  # noqa: F401` in `main.py` is an intentional side-effect import: SQLAlchemy only registers cache tables with `Base.metadata` if the module is imported before `init_db()` runs. Removing or reordering that import will silently drop the cache tables on startup.

Tables:

**Sync tables:**
- `task_sync_map` — maps `airbox_task_id` (int) ↔ `clickup_task_id` (str)
- `agreement_sync_map` — maps `airbox_agreement_id` (int) ↔ `clickup_list_id` (str)
- `sync_log` — audit trail for sync operations

**Cache tables** (in `cache_models.py`, imported in `main.py` so `init_db` picks them up):
- `clickup_space_cache`, `clickup_folder_cache`, `clickup_list_cache`, `clickup_task_cache`, `clickup_user_cache`
- `cache_refresh_log` — tracks each refresh run (trigger, duration_ms, counts, errors)
- `discipline_weights` — per-list EVM weights set via `POST /disciplines/folder/{id}` (FK to `clickup_list_cache.list_id`)

**Civil works tables** (in `civil_models.py` + `progress_models.py`, both imported in `main.py`):
- `civil_project`, `civil_site` — top-level entities; `civil_site.profile_id` FK → `civil_progress_profile`
- `civil_daily_report` — one per (site, date); auto-sequential `report_number` per site
- `civil_resource`, `civil_activity`, `civil_material`, `civil_occurrence`, `civil_quality_check`, `civil_photo`, `civil_next_day_plan`, `civil_signature` — all cascade-delete from `civil_daily_report`
- `civil_progress_profile`, `civil_progress_category`, `civil_progress_activity_def` — EVM profile catalog
- `civil_site_activity_qty` — planned totals per (site, activity_def); unique on (site_id, activity_def_id)
- `civil_progress_measurement` — daily measurements; unique on (site_id, activity_def_id, date)

## Key Configuration

| Variable | Purpose | Default |
|---|---|---|
| `CLICKUP_API_TOKEN` | ClickUp personal API token (required) | — |
| `CLICKUP_TEAM_ID` | ClickUp workspace/team ID (required) | — |
| `CLICKUP_DEFAULT_SPACE_ID` | Space ID — enables polling worker and cache worker when set | `""` |
| `CLICKUP_WEBHOOK_SECRET` | HMAC secret for webhook signature; empty = skip verification (dev only) | `""` |
| `AIRBOX_API_KEY` | API Key do AltoQI Visus Workflow (required) | — |
| `AIRBOX_BASE_URL` | Airbox API base URL — use `https://workflow-api.altoqivisus.com.br` in production | `https://api.airbox.tech` |
| `AIRBOX_DEFAULT_ENTITY_TYPE` | Entity type when creating Airbox tasks | `Agreement` |
| `DATABASE_URL` | SQLAlchemy async URL (SQLite only). In production, point at the mounted Volume: `sqlite+aiosqlite:////data/sync.db` | `sqlite+aiosqlite:///./sync.db` |
| `POLLING_INTERVAL_SECONDS` | ClickUp → Airbox sync interval | `60` |
| `SYNC_ENABLED` | Set to `false` to disable polling worker | `true` |
| `DASHBOARD_ENABLED` | Enable dashboard cache worker | `true` |
| `CACHE_REFRESH_INTERVAL_SECONDS` | How often to refresh ClickUp cache | `300` |
| `CACHE_REFRESH_ON_STARTUP` | Run a cache refresh immediately on startup | `true` |
| `SSE_KEEPALIVE_SECONDS` | Interval between SSE ping events | `15.0` |
| `LOG_LEVEL` | Loguru log level | `INFO` |
| `APP_ENV` | Environment tag (`development` / `production`) | `development` |
| `APP_PORT` | Port hint (informational; actual port set via uvicorn CLI) | `8000` |
| `CHAT_ENABLED` | Enable the AI assistant (`/assistente` + `POST /chat`) | `true` |
| `ANTHROPIC_API_KEY` | Anthropic API key — required for chat; if empty, chat returns 503 | `""` |
| `CHAT_MODEL` | Claude model used by the agent | `claude-haiku-4-5-20251001` |
| `CHAT_MAX_ITERATIONS` | Max tool-use iterations per request | `5` |
| `CHAT_MAX_TOKENS` | Max output tokens per Claude call | `1024` |
| `CIVIL_UPLOADS_DIR` | Directory for RDO photo uploads; served at `/uploads`. In production, point at the mounted Volume: `/data/uploads` | `./uploads` |
| `EMAIL_ENABLED` | Ativar envio automático de relatório semanal por email | `false` |
| `EMAIL_SMTP_HOST` | Servidor SMTP | `smtp.gmail.com` |
| `EMAIL_SMTP_PORT` | Porta SMTP (STARTTLS) | `587` |
| `EMAIL_USER` | Conta Gmail do remetente | `""` |
| `EMAIL_PASSWORD` | App Password do Google (não a senha normal da conta) | `""` |
| `EMAIL_FROM` | Nome e email do remetente (ex: `U2 Broadcast Angola <email@gmail.com>`) | `""` |
| `EMAIL_RECIPIENTS` | Destinatários separados por vírgula | `""` |
| `EMAIL_REPORT_WEEKDAY` | Dia da semana do envio (0=segunda … 6=domingo) | `6` |
| `EMAIL_REPORT_HOUR` | Hora UTC do envio | `8` |

## mapper.py Constants (require manual setup)

In `src/services/mapper.py`, four constants must be configured before production use:

```python
# UUIDs dos custom fields no ClickUp (obtidos via GET /list/{id}/field após criar os campos)
CLICKUP_FIELD_AIRBOX_TASK_ID: str | None = None   # → stores Airbox task ID on ClickUp task
CLICKUP_FIELD_AIRBOX_STAGE_ID: str | None = None  # → stores Airbox stage ID on ClickUp task

# Status name (ClickUp) → task_stage_id (Airbox)  — used when syncing FROM ClickUp
CLICKUP_STATUS_TO_AIRBOX_STAGE: dict[str, int] = {}

# task_stage_id (Airbox) → status name (ClickUp)  — used when syncing TO ClickUp
AIRBOX_STAGE_TO_CLICKUP_STATUS: dict[int, str] = {}
```

**Discovery workflow:** run the first sync with empty dicts → inspect the "Airbox Stage ID" custom field on created ClickUp tasks → fill in the real int IDs.

## Deploy (Railway)

`Procfile`: `web: uvicorn src.main:app --host 0.0.0.0 --port $PORT`

`railway.toml`: builder `nixpacks`, healthcheck at `/health` (timeout 300s), restart policy `on_failure` (max 10 retries). Volumes cannot be declared in `railway.toml` — they must be added via the Railway dashboard (Service → Settings → Volumes) or the Railway CLI (`railway volume add`).

**Database persistence — required setup, not automatic**: add a Volume mounted at `/data` on the web service, then set on that service's environment variables:
- `DATABASE_URL=sqlite+aiosqlite:////data/sync.db`
- `CIVIL_UPLOADS_DIR=/data/uploads`

Without the Volume, the app still runs (SQLite creates the file happily on local disk), but every RDO, project, site, and cached ClickUp row is wiped the next time Railway redeploys the container — there is no warning, the app just starts fresh and empty.

## Airbox API

- **Base URL:** `https://workflow-api.altoqivisus.com.br` (set `AIRBOX_BASE_URL` in `.env`)
- **Auth:** API Key in header `apikey` (generated at AltoQI Visus Workflow → Configurações → Integrações)
- **Key entities:**
  - `Agreement` (type: `project` | `procedure` | `service`) → maps to ClickUp List
  - `Task` (belongs to agreement via `entity_type` + `entity_id`) → maps to ClickUp Task
  - `entity_type` when creating tasks must be `"Agreement"` (not `"project"`, `"procedure"`, etc.)
- **Limitation:** no `PATCH /tasks` — updates from ClickUp cannot be written back

## Testing

Tests use `pytest-asyncio` (mode: `auto`) and `pytest-httpx` for mocking httpx HTTP calls. Env vars for tests are defined in `pytest.ini` via the `env =` directive — this requires the **`pytest-env`** package, which is not in `requirements.txt`; install it with `pip install pytest-env`. No `.env` file needed when running tests.

Unit tests:
- `test_mapper.py` — all mapping functions (ClickUp ↔ Airbox)
- `test_webhook_signature.py` — HMAC signature verification logic
- `test_chat_tool_routing.py` — `get_recent_changes` and `list_tasks_by_status` repository methods against an in-memory SQLite DB (no mocks, uses real ORM)
- `test_dashboard_service.py` — DashboardService read methods
- `test_event_broadcaster.py` — asyncio pub/sub broadcast logic
- `test_cache_service.py` — CacheService refresh and webhook patch logic
- `test_cache_repository.py` — CacheRepository upsert and query methods

Unit tests:
- `test_civil_progress.py` — pure EVM calculation functions from `progress_service.py` (pct, contribution, site/global progress)
- `test_rdo_feeds_progress.py` — verifies that creating a RDO with `activity_def_id` automatically upserts measurements

Integration tests:
- `test_webhook_cache_update.py` — full webhook → cache → SSE path against a real in-memory DB
- `test_dashboard_endpoints.py` — `/dashboard/*` endpoint responses with seeded cache data
