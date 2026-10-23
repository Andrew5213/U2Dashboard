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
│   ├── progress_models.py   # ORM: CivilProgressProfile, CivilProgressCategory, CivilProgressActivityDef, CivilSiteActivityQty, CivilProgressMeasurement
│   ├── authorization_models.py # ORM: AuthorizationToken (links de decisão de uso único)
│   └── schedule_models.py   # ORM: ScheduleTaskState (último %/status visto pelo motor) + ScheduleBaseline (plano)
├── repositories/
│   ├── sync_repository.py   # DB access for sync tables
│   ├── cache_repository.py  # DB access for cache tables (upsert_space/folder/list/task/user, weighted progress, discipline weights)
│   ├── civil_repository.py  # DB access for all civil + progress tables (shared by civil.py, progress_civil.py, civil_service.py)
│   └── authorization_repository.py # Token pairs for service authorizations (create/consume)
├── services/
│   ├── airbox_client.py     # httpx async client for Airbox API
│   ├── clickup_client.py    # httpx async client for ClickUp REST API v2
│   ├── mapper.py            # Field mapping ClickUp ↔ Airbox + stage/status constants
│   ├── sync_service.py      # Orchestrates sync logic ClickUp → Airbox
│   ├── cache_service.py     # Refreshes local SQLite cache from ClickUp API
│   ├── event_broadcaster.py # In-process asyncio pub/sub for SSE events
│   ├── dashboard_service.py # Reads from cache tables to serve dashboard API
│   ├── report_service.py    # Generates PDF reports via fpdf2 (ReportService + ProvinceReportService + PeriodicReportService)
│   ├── gantt_report_service.py # PDF de Gantt de uma província (paisagem), reaproveita o _Report de report_service
│   ├── report_strings.py    # Bilingual string dictionaries for PDF text (PT/EN), keyed by get_strings(lang)
│   ├── translation.py       # Static PT→EN dict for ClickUp field names (disciplines, activities, statuses) via translate()
│   ├── weights_config.py    # EVM weight constants + compute_province_progress / compute_list_progress / build_province_evolution
│   ├── chat_service.py      # Agentic loop: Claude Haiku + tool use → ChatResponse (with optional ChartPayload)
│   ├── chat_tools.py        # TOOL_DEFINITIONS (9 tools) + dispatch_tool() routing to DashboardService/CacheRepository
│   ├── email_service.py     # EmailService: builds MIME email, attaches PT+EN PDFs, sends via SMTP (asyncio.to_thread)
│   ├── civil_service.py     # CivilService: orchestrates RDO creation (nested children, sequential numbering, auto-fill measurements)
│   ├── progress_service.py  # ProgressService + pure EVM functions (pct, activity_contribution, global_progress)
│   ├── rdo_pdf_service.py   # generate_rdo_pdf(report, site_name) → bytes — fpdf2-based RDO PDF
│   ├── smtp_sender.py       # send_smtp() — envio SMTP compartilhado (relatórios + autorizações)
│   ├── authorization_service.py # Autorização de serviço: e-mail ao gestor → decisão → ClickUp
│   ├── schedule_engine.py   # Motor do cronograma (puro): calendário, datas, reprogramação, % × status
│   ├── schedule_fields.py   # Campos do ClickUp usados pelo cronograma (casados por nome)
│   ├── schedule_service.py  # Lê a lista, roda o motor e grava só as diferenças
│   ├── schedule_xlsx.py     # Leitura das planilhas PMEx (importador e fixture de teste)
│   ├── schedule_xlsx_sitetype.py # Planilhas de tipos de site de transmissão (Type 1–4, com Peso %)
│   └── authorization_emails.py  # HTML dos e-mails de pedido e de decisão
├── api/
│   ├── health.py            # GET /health
│   ├── auth.py              # GET /auth/me — quem está a ver, pelo JWT do Nextcloud (identificação, não login)
│   ├── sync.py              # POST /sync/trigger, GET /sync/status|logs, GET+POST /sync/mappings/agreements
│   ├── webhooks.py          # POST /webhooks/clickup — verifies HMAC, syncs to Airbox, updates cache + SSE
│   ├── dashboard.py         # GET /dashboard/overview|folders|folder/{id}|list/{id}|task/{id}|assignees|upcoming|evolution
│   │                        #   GET /dashboard/gantt/{list_id}|gantt/folder/{id}|gantt/task/{id}
│   │                        #   GET /dashboard/gantt/folder/{id}/detail — o Gantt do PDF em JSON, para a tela
│   │                        #   POST /dashboard/refresh
│   ├── dashboard_stream.py  # GET /dashboard/stream (Server-Sent Events)
│   ├── reports.py           # GET /reports/pdf, /reports/pdf/provincia, /reports/pdf/daily, /reports/pdf/weekly, /reports/folders
│   │                        #   POST /reports/email/send — manual trigger for weekly email (fires in background)
│   ├── disciplines.py       # GET/POST/DELETE /disciplines/folder/{folder_id}
│   ├── chat.py              # POST /chat, GET /chat/status
│   ├── civil.py             # /civil/* — Projects, Sites, DailyReports (RDO), photo upload
│   ├── progress_civil.py    # /civil/progress/* — Profiles, Categories, ActivityDefs, Quantities, Measurements, progress summaries
│   ├── authorizations.py    # POST /webhooks/autorizacoes + GET/POST /autorizacoes/decidir/{token}
│   └── schedule.py          # GET /schedule/lists, POST /schedule/{list_id}/recalculate, POST /schedule/{list_id}/baseline
└── workers/
    ├── polling_worker.py    # APScheduler: ClickUp → Airbox sync on interval
    ├── cache_worker.py      # APScheduler: refreshes local ClickUp cache on interval
    ├── email_worker.py      # APScheduler: sends weekly PDF report via email on configured weekday/hour UTC
    └── schedule_worker.py   # Recálculo do cronograma: por webhook (debounce) e periódico
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
- `taskDeleted` → logged but not propagated to Airbox (no `DELETE /tasks` either); the local cache row **is** removed (`CacheService.apply_webhook_event` special-cases this event — it skips re-fetching from ClickUp, since the task no longer exists there, and calls `CacheRepository.delete_task` directly)

After each handled webhook event, the cache is updated and an SSE broadcast fires (fire-and-forget — does not block the response). `HANDLED_EVENTS` in `webhooks.py` must list every event ClickUp is configured to send (see `scripts/register_webhook.py`) — an event ClickUp sends but this set omits is silently dropped with no cache update, which is exactly how `taskDeleted` was missed before this was added: the webhook was already registered for it, the handler just never listened.

**Webhook signature** (`src/core/webhook_security.py::verify_clickup_signature`, shared by `/webhooks/clickup` and `/webhooks/autorizacoes`): ClickUp sends `X-Signature` as the **plain hex** HMAC-SHA256 of the raw body — **no `sha256=` prefix** ([docs](https://developer.clickup.com/docs/webhooksignature)). With a secret configured the header is mandatory (missing or wrong → 401 on `/webhooks/clickup`, `{"status": "invalid_signature"}` on `/webhooks/autorizacoes`); with an empty secret verification is skipped (local dev only — **always set `CLICKUP_WEBHOOK_SECRET` / `AUTHORIZATION_WEBHOOK_SECRET` in production**, otherwise anyone can post forged events). Tests must import the real function — an earlier test copy-pasted its own `verify_signature` and so never caught a wrong format.

**`SYNC_ENABLED=false` also gates the webhook**: `/webhooks/clickup` skips `SyncService` (Airbox) entirely and only updates the cache + SSE broadcast. Before this, every `taskCreated` called `airbox.list_agreements()` regardless of the flag.

**Deleted-task pruning on cache refresh**: `CacheRepository.mark_tasks_stale(list_id, seen_ids)` diffs the full task list against what ClickUp currently returns (which includes subtasks, since `get_tasks()` always passes `subtasks=true`) and deletes any cached row not in that set — this covers both top-level tasks and subtasks with no parent-vs-subtask distinction. (This method used to filter to `parent_task_id IS NULL` only, so a subtask deleted in ClickUp was never pruned by a refresh, only ever by the `taskDeleted` webhook above — the two paths are now consistent.)

**Cache refresh reads first, writes later**: `refresh_cache_full` fetches every folder, list and task from ClickUp into memory (`_fetch_folders`, ~150 s for the space) and only then upserts everything in one short transaction. It used to upsert while walking, holding SQLite's write lock for the whole walk — the schedule engine (same database, `busy_timeout` 30 s) failed with `database is locked` every 30 minutes in production, after it had already written to ClickUp, which could turn its own dates into "typed" edits on the next run. `test_refresh_full_does_not_hold_the_database_while_reading_clickup` guards it.

**Deleted-list/folder pruning on cache refresh**: `CacheService.refresh_cache_full` collects every folder/list ID actually returned by the ClickUp API during the walk, then calls `CacheRepository.mark_lists_stale(space_id, seen_list_ids)` and `mark_folders_stale(space_id, seen_folder_ids)` once at the end to delete any cached folder/list not in those sets. There is no webhook equivalent for list/folder deletion (ClickUp doesn't send one), so a deleted list/folder only disappears from the dashboard/reports after the next full refresh (`cache_worker` interval, `POST /dashboard/refresh`, or app restart) — never immediately. SQLite doesn't enforce foreign keys here, so `mark_lists_stale` manually cascades: it deletes the list's tasks and `discipline_weights` rows before deleting the list row itself.

## Dashboard & Cache Layer

The app maintains a local SQLite cache of the ClickUp space structure to serve the dashboard UI without hitting the ClickUp API on every page load.

**Cache refresh sources:**
1. `cache_worker.py` — APScheduler job, runs every `CACHE_REFRESH_INTERVAL_SECONDS` (default 300s). Enabled when both `DASHBOARD_ENABLED=true` and `CLICKUP_DEFAULT_SPACE_ID` is set. On first run (`CACHE_REFRESH_ON_STARTUP=true`) fires immediately.
2. `POST /dashboard/refresh` — triggers a full cache refresh in background.
3. Webhook events — `CacheService.apply_webhook_event()` patches individual tasks in the cache, then broadcasts via SSE.

**SSE stream**: `GET /dashboard/stream` — clients receive `update` events (with `type`, `task_id`, `list_id`) whenever a webhook updates a task. Sends `ping` keepalives every `SSE_KEEPALIVE_SECONDS` (default 15s).

**Dashboard UI**: served at `GET /` via `src/templates/index.html` (or `index_mobile.html`). The frontend calls `/dashboard/*` REST endpoints and connects to `/dashboard/stream` for live updates.

**Geração de navegação (`_gen` em `app.js`)** — toda tela nova tem de respeitar.
`router()` incrementa `_gen` a cada navegação; cada `render*` captura `const gen = _gen;` na
**primeira linha** e passa esse `gen` a todo `setView(html, gen)`. `setView` recusa pintar (devolve
`false`) quando a geração já não é a corrente, e quem desenha gráfico depois confere
`isCurrent(gen)` dentro do `requestAnimationFrame`.
- **Porquê**: todo `render*` é assíncrono — pinta só depois do `await api(...)`. Sem isto, quem
  voltasse por último ficava na tela: sair de uma província lenta para uma rápida deixava a lenta
  pintar por cima da que o utilizador acabara de abrir (reproduzível com `location.hash = '#/'`
  seguido, 300 ms depois, de `#/gantt/folder/<id>`: a visão geral chegava ~800 ms depois e tapava o
  Gantt). Vale também para o SSE e para o *polling fallback*, que chamam `router()` por conta
  própria enquanto um render pode estar em voo.
- **Função nova que esquece o `gen`** não quebra nada visivelmente — só volta a poder pintar por
  cima de uma tela mais recente. `setView` sem `gen` pinta sempre, de propósito: é o caso de quem
  redesenha a pedido do utilizador já dentro da tela (o filtro de província em `renderAssignee`,
  que passa o `gen` capturado no fecho).
- `_renderGanttView` recebe a geração em `opts.gen`, porque é um ajudante partilhado por duas telas.

**Completion-rate unit of measure**: `get_overview_kpis`, `get_folders_with_metrics`, `get_lists_with_metrics`, `get_gantt_overview`, `get_folder_kpis`, `get_assignee_task_stats`, and `get_assignee_stats_by_folder` (`cache_repository.py`) count progress in terms of "leaf tasks" — via the `_leaf_tasks_clause()` helper (task_id not present as anyone's `parent_task_id`) — not top-level tasks. This means a top-level task (Discipline) with subtasks is excluded from the count and its subtasks (Activities) are counted instead; a top-level task with no subtasks still counts as itself. This affects the overview KPIs, province/module cards, the status donut, the general Gantt, the AI assistant's per-province progress tool, and every PDF/XLSX report's completion percentages (executive + província summary cards, team performance table) — all now measure progress at Activity granularity rather than Discipline granularity. Listing-style queries (`get_overdue_tasks_by_folder`, `get_upcoming_tasks_by_folder`, `get_overdue_tasks_detail`, `get_tasks_by_status`, `get_recent_changes`, `get_period_updates`) were intentionally left on top-level-only filtering, since they enumerate individual task rows rather than compute a percentage (exception: on schedule lists the overdue/upcoming listings enumerate leaf tasks — see "Cronograma de Obra → Relatórios"). The weighted EVM system (`weights_config.py`) is unaffected — it already worked from subtasks.

**Mobile template selection** (`main.py`): `_is_mobile()` checks the `?view=` query param first (`desktop` or `mobile` to force), then falls back to user-agent sniffing for `mobile/android/iphone/ipad/ipod`. `GET /` and `GET /assistente` follow this pattern. `/rdo` and `/progresso-civil` do not have mobile variants (no mobile UI was ever built for the RDO module).

**Mobile navigation**: both mobile templates (`index_mobile.html`, `chat_mobile.html`) share the same hamburger-menu pattern instead of a persistent bottom tab bar (a bottom nav was tried first but conflicted with chat's fixed input bar, so it was replaced everywhere for consistency). Each page has a `.mob-menu-btn` in the header that calls `openMenu()`, opening a `.mob-drawer#main-menu` with links to Dashboard, Assistente IA (conditional on `chat_enabled`), Cronogramas, plus buttons for Relatórios (closes the menu and opens the reports drawer) and Atualizar Cache. The reports drawer itself (`#reports-drawer` + `openDrawer`/`closeDrawer`/`setReportLang`/`exportPDF`/`exportDiario`/`exportSemanal`/`toggleProvinciaDrawer`/`exportProvincia`) and `triggerRefresh()` are duplicated verbatim into both templates — same copy-per-page convention already used for the desktop sidebar, since there's no shared-partial/include mechanism in this template-per-page architecture. `chat_mobile.html` did not have `#mob-toast`/`showToast()` before this and needed them added for `triggerRefresh()`'s feedback.

**Tema escuro (paleta do hub U2)**: toda a UI segue as cores de
`u2broadcast.engenhariarf.com` — `--u2-black #0a0a0b` (fundo), `--u2-ink #111113` (sidebar),
`--u2-panel #161618` (cards), `--u2-line #2a2a2e` (bordas), `--u2-gray #8b8b93`,
`--u2-white #f4f4f2`, `--u2-red #e8262a` (acento único: azuis e índigos de ação viram vermelho),
mais as fontes Archivo e JetBrains Mono. As variáveis vivem em `src/static/theme-dark.css`.

Como a app é Tailwind play CDN com utilitárias espalhadas por 8 templates, o tema **não** reescreve
classes: `theme-dark.css` remapeia as ~95 utilitárias de cor que a app usa, todas sob `.theme-dark`
— especificidade (0,2,0) contra a (0,1,0) do Tailwind, o que dispensa `!important`. A classe entra no
`<body>` de cada template; **removê-la devolve o visual claro**. Três exceções em que o seletor de
classe simples empata e perde (o play CDN injeta seu `<style>` depois dos nossos `<link>`): regras que
atingem o próprio elemento do tema usam `body.theme-dark` / `.theme-dark.bg-gray-100`.

O `<style>` interno de `chat.html`/`rdo.html` e o `mobile.css` não são Tailwind: os componentes do chat
e do RDO ganharam override nominal no mesmo arquivo, e `mobile.css` foi convertido na origem para as
variáveis (o mobile não tem variante clara). Regras com `!important` em `rdo.html` (`.field-input.status-*`)
e cores atribuídas por JS via `element.style.background` furam qualquer override — essas foram trocadas
no próprio arquivo.

**ECharts não resolve CSS custom properties.** Dentro de `option` (itemStyle, axisLabel, splitLine,
textStyle) a cor precisa ser literal — `var(--u2-...)` ali faz a série sumir sem erro no console. O tema
dos gráficos é registrado em `src/static/echarts-theme-u2.js` (carregado por `index`, `chat`,
`index_mobile` e `chat_mobile`, antes de `charts.js`) e aplicado via `echarts.init(el, U2_DARK() ? 'u2dark' : null)`.
Fica fora de `charts.js` porque o chat não carrega aquele arquivo.

**Assets são versionados à mão** com `?v=N` nos templates. Esquecer de incrementar depois de mexer em
CSS/JS faz o navegador servir o arquivo antigo — vale para o deploy e para o teste local.

**Modo embutido (Nextcloud › External sites)**: o External sites abre a app num `<iframe id="ifm" allowfullscreen>`
simples, sem `sandbox` — downloads, SSE e `target="_blank"` funcionam sem ajuste. O que muda é a moldura: a
barra superior, a marca e o menu de apps já são do Nextcloud, e sobra menos área. `src/static/embed.js` +
`embed.css` (carregados nos 6 templates de dashboard/assistente, logo depois de `theme-dark.css`)
detectam o iframe (`window.self !== window.top`) e põem a classe `embed` no `<html>`; **fora de um iframe não
fazem nada** — o layout com barra lateral é o mesmo de antes (tag `backup/layout-pre-nextcloud`).
- **Desktop**: a `<aside>` vira o painel "Relatórios", que desliza pela direita (botão no topo, fecha com Esc
  ou clique fora); os links de navegação dela são copiados para abas na barra do topo (44 px em vez de 56) e o
  logo some. Nada é duplicado nos templates: o `embed.js` monta as abas lendo os `<a>` que vêm antes do bloco
  de relatórios (o que contém `#lang-pt`) — link novo na barra lateral vira aba sozinho.
- **Diálogos**: `prompt()`/`confirm()` foram trocados por `U2Dialog.prompt/confirm` (assíncronos). Fora do
  iframe chamam os nativos; dentro, abrem um diálogo da própria página — num iframe de outra origem os nativos
  aparecem como "uma página incorporada diz…" e podem ser bloqueados pelo navegador. Os módulos desligados
  (`rdo.html`, `progress_civil.html`) ainda usam os nativos e não carregam o `embed.js`.
- **Mobile (Nextcloud no celular)**: o template mobile já era escolhido pelo user-agent dentro do iframe; o
  modo embutido só o ajusta (`html.embed .mob-*` em `embed.css`): cabeçalho de 44 px em vez de 52, sem o
  `padding-top` do safe-area (o entalhe é do Nextcloud) e sem o logo. A navegação segue no menu em gaveta e o
  nome de quem está a ver (JWT) aparece no título dessa gaveta — `showUser` em `embed.js` cai nela quando não
  há o botão "Relatórios" do desktop. Uma barra de abas fixa embaixo já foi tentada e brigava com a caixa de
  texto do assistente.
- **Teste sem Nextcloud**: `?embed=1` força o modo e `?embed=0` desliga (a escolha fica em `sessionStorage`
  até fechar a aba).
- **Quem pode embutir**: `EMBED_ALLOWED_ORIGINS` (ex.: `https://cloud.exemplo.com`) faz toda resposta levar
  `Content-Security-Policy: frame-ancestors 'self' <origens>` (`src/core/embed_security.py`, middleware ASGI
  puro para não mexer no streaming do SSE). Vazio = sem cabeçalho, qualquer site pode embutir. O nginx do
  servidor não envia `X-Frame-Options`; se alguém acrescentar, o iframe para de abrir.
- **No Nextcloud**: Administração → External sites → nome, URL
  `https://u2dashboard.engenhariarf.com/?jwt={jwt}`, sem marcar "redirect". O template mobile continua
  sendo escolhido pelo user-agent, também dentro do iframe.

**Quem está a ver (JWT do Nextcloud)** — `src/core/nextcloud_auth.py` + `GET /auth/me`. O External sites
troca o `{jwt}` da URL por um token **ES256** assinado pela instância, válido por 1 hora, com
`iss`, `iat`, `exp` e `userdata: {uid, email, displayName}`. A app só confere a assinatura com a chave
**pública** (`NEXTCLOUD_JWT_PUBLIC_KEY_PEM`) — não há segredo partilhado. **É identificação, não login**:
não há sessão no servidor nem permissão nenhuma; token ausente ou inválido = anónimo, e a app funciona
igual. Sem a chave configurada a verificação fica desligada.
- **Fluxo**: `embed.js` tira o `jwt` da barra de endereço logo na carga (`history.replaceState` — não fica
  no histórico nem em link copiado), guarda-o em `sessionStorage` (só nesta aba, para a identificação
  acompanhar a troca de página dentro do iframe) e chama `GET /auth/me` com o cabeçalho
  `X-Nextcloud-JWT`. O servidor valida a cada chamada; a resposta vira `window.U2User`, o evento
  `u2-user` e o nome na barra do topo (modo embutido, desktop). Cada identificação gera uma linha de log
  `Nextcloud: <uid> (<nome>) abriu <página>`; o token nunca é logado.
- **`algorithms=["ES256"]` é fixo** em `verify_token`. Aceitar o algoritmo que o próprio token declara
  abriria o ataque clássico do HS256 "assinado" com a chave pública. `exp` e `iat` são obrigatórios
  (30 s de tolerância de relógio); `NEXTCLOUD_JWT_ISSUER`, se preenchido, recusa token de outra instância.
- **Obter a chave** (uma por instância — dev e produção têm pares diferentes):
  `occ config:app:get external jwt_token_pubkey_es256`. Só existe depois de alguém abrir o site externo
  uma vez, porque o par é gerado na emissão do primeiro token. `normalize_public_key` aceita o PEM com
  quebras reais, com `
` por extenso (o que cabe numa linha de `.env`) ou só o base64.
- **Para proteger uma rota no futuro**: a dependência `nextcloud_user` (FastAPI) devolve o utilizador ou
  `None` e nunca bloqueia; exigir login é decidir o que fazer com o `None` — hoje ninguém faz.
- O `jwt` chega primeiro na query string do `GET /`, então **aparece no access log do nginx** — vale 1 hora
  e só identifica, mas é o motivo para não reaproveitar esse token como credencial de nada.

**Números da visão geral — o que cada um mede**: "Concluídas" conta tarefas-folha (773 de 2349 =
32,9%); "Progresso Geral" é a **média ponderada das províncias** (cada província vale igual), por isso
os dois percentuais diferem e cada cartão diz qual é o seu. Na rosca de status todos os status entram
(o "planejando" já veio oculto por padrão e a rosca parecia toda concluída), e nas barras de progresso
em percentual só a parte concluída leva rótulo (o "100%" da parte em aberto lia-se como 100% feito).

**Equipes e responsáveis**: os cartões da visão geral (até 6, ordenados por carga nos próximos 7 dias)
e a tela `#/assignee/<nome>` respondem "o que esta equipe tem para fazer agora". `get_assignee_task_stats`
devolve também `in_progress` (aberta e já iniciada — `_is_started`: status de andamento ou % entre 1 e
99) e `next_7_days` (começa ou termina até lá); `get_tasks_by_assignee` devolve `start_date`,
`parent_name` e `is_started`. A tela agrupa as tarefas abertas em janelas (vencidas, em andamento,
próximos 7 dias, 8–30, mais adiante, sem data), com filtro por província; as janelas distantes e as
concluídas começam recolhidas.

**Cronogramas** (`#/gantts`, link próprio no menu lateral, aba no modo embutido e item no menu mobile):
uma linha por província com período, progresso, desvio e três ações — ver o Gantt na tela
(`#/gantt/folder/<id>`), PDF e XLSX (`downloadGantt`). Província sem datas aparece no fim, sem ações,
com o aviso de definir o início da lista. A tela de Gantt da província tem os mesmos dois downloads no
cabeçalho. O período vem de `get_gantt_overview`, cujo início é o primeiro `start_date` real da
província (a data de criação só vale de aproximação quando nenhuma tarefa tem início).

**O Gantt da província na tela é o mesmo do PDF** (`Charts.renderGanttDetail` em `charts.js`,
alimentado por `GET /dashboard/gantt/folder/{id}/detail?lang=`). Esse endpoint chama
`GanttReportService.build_screen_data`, que é o `_build_data` do PDF e do XLSX com as datas em ISO —
os três partem da mesma árvore, das mesmas datas e do mesmo %. **Divergir aqui é o pior dos mundos**:
o cliente olha a tela e imprime o PDF, e os dois mostrariam cronogramas diferentes da mesma província.
- A tela traz os 3 níveis indentados (disciplina → grupo → tarefa), as colunas Início/Término/%, o
  resumo como barra achatada, planejado × executado, a zebra das pausas e a linha de hoje — a mesma
  leitura do PDF. Só a paleta muda: segue o tema escuro da app, senão ficaria um quadro branco no
  meio da página.
- **Não é ECharts**: são divs posicionados por dia dentro de uma tabela com as quatro primeiras
  colunas congeladas (`position:sticky`). A tabela **precisa de `width` explícito** — `table-layout:
  fixed` é ignorado sem ele, e o navegador estica a coluna do nome até caber o nome mais comprido,
  empurrando a linha do tempo para fora da tela.
- A semana estica para ocupar a largura disponível (mínimo 32 px, aí passa a rolar). As linhas de
  `build_gantt_rows` levam `task_id` só para esta tela — clicar abre a tarefa; PDF e XLSX ignoram.
- `GET /dashboard/gantt/folder/{id}` (sem `/detail`) continua a devolver só as tarefas de topo e
  serve as outras duas telas de Gantt, a da lista (`#/gantt/<list_id>`) e a da tarefa
  (`#/gantt/task/<id>`), que seguem no gráfico simples de semanas.

**Busca** (`GET /dashboard/search?q=`, campo na barra do topo do dashboard desktop, atalho `/`):
todas as palavras têm de aparecer no nome, sem diferenciar caixa nem acento. O filtro é em Python
(`_search_key`) porque o `LIKE` do SQLite só ignora caixa em ASCII. O mobile ainda não tem busca nem
a tela por equipe.

**Versão em inglês** — `src/static/i18n.js` (motor) + `i18n-en.js` (dicionário) + `GET /i18n/terms.js`
(nomes do ClickUp). A interface continua escrita em português nos templates e no HTML montado em
JavaScript; em inglês, o `i18n.js` traduz **o que chega ao DOM** (nós de texto, `placeholder`, `title`,
`aria-label`, o `<title>`) e acompanha o que é renderizado depois com um `MutationObserver`. Mesma
filosofia do `theme-dark.css` e do `embed.js`: uma camada por cima, sem reescrever 6 templates.
- **Ordem da procura** para cada texto: frases fixas (`i18n-en.js`) → padrões com número/data/nome no meio
  (regex, no mesmo arquivo) → termos do ClickUp (`window.U2_TERMS`, o `_EN` de `translation.py`, o mesmo
  dos relatórios em inglês). Texto com ` · `, ` / ` ou ` — ` é traduzido pedaço a pedaço. Sem
  correspondência fica em português — **frase nova na interface precisa de entrada no `i18n-en.js`**;
  `U2I18n.missing()` no console lista o que foi visto sem tradução.
- **Nome novo no ClickUp** (disciplina, atividade, lista) entra em `translation.py::_EN` (chave normalizada
  por `_norm`) e passa a valer para a tela e para os PDFs/XLSX. `i18n.js::termKey` repete o `_norm`.
- **Idioma**: `?lang=en|pt` (também serve o `{language}` do External sites do Nextcloud), senão a última
  escolha em `localStorage`, senão português. O seletor PT | EN é montado pelo próprio `i18n.js` na barra do
  topo (desktop e mobile) e recarrega a página. Em inglês os relatórios já saem em inglês por padrão
  (`setReportLang('en')`), e `POST /chat` recebe `lang` — o assistente responde no idioma da interface.
- **O que não passa pelo DOM** usa `U2I18n.t()` direto: rótulos de gráfico em `charts.js` (`T(...)`, traduzidos
  antes de o ECharts medir o texto) e as mensagens de `U2Dialog` (o `prompt()` nativo não é DOM).
- **Não traduz** o que é do utilizador: `#chat-messages`, `#mob-chat-messages` e qualquer `[data-no-i18n]`.
  Nomes próprios (províncias, equipes, pessoas) ficam como estão.
- `html.i18n-pending body { visibility: hidden }` segura a primeira pintura até a tradução rodar, para não
  piscar em português. Datas continuam `dd/mm/aaaa` nos dois idiomas.

**Static assets**: `src/static/echarts.min.js` is a locally bundled copy of Apache ECharts — it is not fetched from a CDN. When upgrading ECharts, replace this file manually.

**"Vencimento" / "Data de Conclusão" custom fields are the only source of due date/close date**: the user added two `date`-type custom fields — "Vencimento" and "Data de Conclusão" — to every list in the space, all sharing the same field id (`_FIELD_VENCIMENTO_ID` / `_FIELD_DATA_CONCLUSAO_ID` in `cache_repository.py`, discovered via `GET /list/{id}/field`). `CacheRepository.upsert_task()` reads these via `_custom_field_value()` and uses them as `due_date`/`date_closed` in the cache — **with no fallback** to ClickUp's native `due_date`/`date_closed`. A task without the custom field filled in simply has no due date/close date in the cache, even if it has an old native due date configured (native ClickUp due dates are no longer used anywhere in this app). Every overdue/upcoming/gantt/evolution computation in the app reads `due_date`/`date_closed` from this same cache column, so this single upsert-time change is what makes the whole dashboard and every PDF/XLSX report follow the new fields — no other call site needed to change. If these fields are ever deleted and recreated in ClickUp, the two id constants must be updated (they're per-field-instance, not per-name). Since this only takes effect on the next cache upsert, a task edited before this change was deployed keeps showing its old native due date until the next full refresh (`cache_worker` interval, `POST /dashboard/refresh`, or app restart) re-upserts it.

**"Observações" custom field surfaces as a per-task note button in the dashboard**: another space-wide `short_text` custom field (`_FIELD_OBSERVACOES_ID` in `cache_repository.py`), stored on `ClickUpTaskCache.observacoes` and passed through by `_task_to_summary()` to `TaskSummary.observacoes`. Note there are **two** ClickUp fields named "Observações" in this space — an older `text`-type one scoped to FM Site/Transmissor-type lists (unrelated, not read by this app) and this newer space-wide `short_text` one; only the latter's id is used. In the UI (`app.js`), `noteButton()` renders a small button next to a task/subtask row only when `observacoes` is non-empty (nothing renders otherwise), and `showObservacao()` opens a modal with the full text — wired into both the list view's task rows (`renderList`) and the task-detail view's subtask rows (`renderTask`). The button's `onclick` calls `event.stopPropagation()` so clicking it doesn't also trigger the row's own navigation.

**Schema change is applied automatically**: `observacoes` is a new column on the existing `clickup_task_cache` table — it's picked up on the next app startup by the automatic column-sync described in the Database section (`_sync_missing_columns()`), no manual `ALTER TABLE` needed.

## PDF Reports

Five report types, all generated on-demand using `fpdf2` (Latin-1 fonts — use `_s()` helper to sanitize em-dashes, curly quotes, etc.). Every PDF endpoint accepts `?lang=pt|en` (default `pt`) and `?inline=true` to stream in-browser.

- **`GET /reports/pdf`** — executive report for the full space (cover + summary + project health + overdue + upcoming + team performance). Uses `ReportService`.
- **`GET /reports/pdf/provincia?folder_id=<id>`** — detailed report for a single folder/province (cover + summary + per-list detail with task-level breakdown). Uses `ProvinceReportService`. Incorporates EVM weighted progress when discipline weights are configured.
- **`GET /reports/pdf/gantt?folder_id=<id>`** — Gantt da província em Letter paisagem (timbrado deitado, ver abaixo): tabela (tarefa, início, término, %) à esquerda e barras numa linha do tempo à direita, com a linha de "hoje". Usa `GanttReportService` (`gantt_report_service.py`). Entram todas as listas da pasta que têm tarefas com datas — nas de cronograma, os 3 níveis com as datas do motor; nas comuns, o que houver (início nativo e "Vencimento"), e a tarefa-mãe sem data própria cobre o intervalo das filhas. Lista sem nenhuma data fica fora do gráfico e é citada no rodapé. A grade é sempre semanal: cada semana tem a sua linha e o rótulo `dd/mm` da segunda-feira (só em cronogramas muito longos o rótulo salta semanas, em passo regular). "Hoje" é um marcador sobre a linha vermelha, com a data na legenda — um rótulo ali tapava o da semana ao lado. Na UI é o botão "GANTT" ao lado de cada província no menu de relatórios (desktop e mobile).
- **`GET /reports/xlsx/gantt?folder_id=<id>`** — o mesmo Gantt em planilha (`render_gantt_xlsx`, mesmo `_build_data` do PDF): as barras são **células pintadas**, uma coluna por dia (uma por semana acima de 190 dias), com meses, semanas (`dd/mm` da segunda-feira) e dias no cabeçalho congelado, datas e % como valores de verdade, linhas agrupadas por nível (estrutura de tópicos do Excel) e a coluna de hoje com borda vermelha.
- **`GET /reports/pdf/daily`** — daily updates report (tasks completed/updated yesterday and today). Uses `PeriodicReportService`.
- **`GET /reports/pdf/weekly`** — weekly updates report (last 7 days). Uses `PeriodicReportService`.
- **`GET /reports/folders`** — lists folders available for province reports (reads from cache).

Bilingual support: `report_strings.py` holds all UI strings keyed by `get_strings(lang)`. `translation.py` maps normalized Portuguese field names → English equivalents via `translate()` / `translate_task_row()`.

**Papel timbrado da GatesAir em todas as páginas** (`src/services/letterhead.py`): o timbrado veio do
cliente como PDF **vetorial** (`src/assets/letterhead.pdf`, um único `/Form` XObject, zero imagens raster),
então em vez de redesenhar a logo e a faixa com fpdf2 — o que exigiria exportá-las como imagem e perderia
nitidez na impressão — `stamp()` põe o timbrado **por baixo** de cada página gerada (`page.add_underlay()`
do pikepdf, daí a dependência nova no `requirements.txt` — **o servidor precisa de `pip install -r
requirements.txt` no próximo deploy**). A logo sai idêntica ao original em qualquer zoom.
- **Os relatórios são Letter, não A4** (`PAGE_W, PAGE_H = 215.9, 279.4`). É o formato do timbrado; esticar
  Letter (612×792 pt) para A4 (595×842) pede fatores diferentes em x e y e distorceria a logo.
- **As margens vêm do timbrado**, medidas no próprio PDF e exportadas como constantes: `TOP_MM = 37.7`
  (onde acaba o bloco das logos), `FOOTER_TOP_MM = 266.3` (onde começa a faixa vermelha), `SIDE_MM = 12.5`.
  `report_service` deriva `CONTENT_BOTTOM = FOOTER_TOP_MM - 14` delas, e **todo limite de quebra de página
  usa `CONTENT_BOTTOM - <folga>`**: os 12 literais de A4 que havia antes (`if row_y > 255`) fizeram o
  relatório executivo passar de 8 para 19 páginas quando as margens mudaram.
- **A logo da U2 entra ao lado da GatesAir** (`src/assets/u2-logo.png`), composta em memória por `_template()`
  — o `letterhead.pdf` continua a ser exatamente o ficheiro que o cliente forneceu, intocado.
- **Paisagem (Gantt)**: não dá para girar o timbrado (a logo ficaria de lado) nem para esticá-lo, então
  `_landscape_template()` desenha o mesmo Form XObject **três vezes, recortado**: as logos só descem; o
  bloco de endereço e o ícone da faixa também andam para a direita, para continuarem encostados à margem;
  o vão liso que sobra na faixa é pintado com `#C42032`, com 2 pt de sobreposição para a emenda não virar
  um fio claro ao arredondar para pixel. São **dois cortes diferentes** (`LEFT_CUT = 470`,
  `RIGHT_CUT = 600`) e não um só: um corte único deixava um pedaço da logo da U2 repetido no meio da página.
- **`stamp()` falha com elegância**: ficheiro em falta ou PDF ilegível → o relatório sai sem timbrado, com
  um log de erro, em vez de rebentar o download.
- **A paleta dos relatórios é a do timbrado**: `INK = #1A1A1A` e `ACCENT = #C42032` (era o azul
  institucional), nos PDF, nos XLSX (`xlsx_utils.py` — `NAVY`/`BLUE` passaram a `INK`/`ACCENT`) e no HTML do
  e-mail semanal.
- **O vermelho é só do timbrado.** Nenhuma faixa desenhada pela app é vermelha: a única é a do rodapé, que
  vem do próprio papel. No Gantt, a faixa de título, o cabeçalho de tabela e a linha de lista usam `INK`
  (`HEAD_BG`), o mesmo cinza-chumbo de `_table_header` e `_schedule_report_header` nos outros relatórios.
- **As cores do gráfico do Gantt não seguem a paleta**: `BAR_DONE` azul, `_TRACK` azul claro, `GREEN` e
  `RED` são codificação de dado, não moldura — no vermelho do timbrado a parte executada da barra ficaria
  igual à de atraso. Por isso vivem em constantes **locais** de `gantt_report_service.py`, e não importadas:
  trocar a paleta em `report_service` não as alcança.
- **A continuação do Gantt começa em `_TOP`, não no topo da página**: o timbrado põe as logos em **toda**
  página, e a tabela da segunda em diante passava por cima delas (`test_continuation_page_starts_below_the_letterhead`).
- O timbrado traz o endereço da GatesAir em Cincinnati em todo relatório da U2. **É intencional** — o
  cliente confirmou em 21/10/2026 que fica assim; não é um descuido a corrigir.

**No "created" category — periodic reports and the AI assistant only show real progress**: `CacheRepository.get_period_updates()` (daily/weekly PDF/XLSX) and `get_recent_changes()` (chat assistant tool) used to have a third "created" bucket for newly-created tasks still sitting in their initial status. That bucket was removed entirely — a task/subtask only appears in these reports if it's either `concluded` (closed in the period) or `updated` with its **current** status normalized to one of `_REPORTABLE_UPDATE_STATUSES` in `cache_repository.py` (`fazendo`, `revisão`, `aprovação`, `concluído`/`complete`). Anything still sitting in `planejando` (or any other status outside that list, e.g. `aguardando`/`bloqueado`/`cancelado`) is silently dropped — it never shows up as a "recent change," no matter when it was created or last touched. This also drives the AI assistant: `get_recent_changes` no longer returns a `created` key at all, and its tool description explicitly tells Claude never to mention newly-created tasks.

In `get_period_updates()`, when a subtask qualifies but its parent task doesn't (the common case — the Discipline itself rarely gets a reportable status change, only its Activities do), the parent is still rendered as a normal container row with the subtask nested/indented beneath it, keyed by `(parent_task_id, category)` in `parent_shells` — it is **not** collapsed into a single flattened `"Pai > Subtarefa"` row. If the parent's own subtasks split across categories (e.g. one activity concluded, another still in progress), it gets one shell per category so each nests under the correct report section.

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

**Overriding weights via API**: `POST /disciplines/folder/{folder_id}` saves per-list weights (0.0–1.0, must sum to 1.0) to the `discipline_weights` DB table. `GET /disciplines/folder/{folder_id}` returns current weighted progress (no password needed — read-only). When DB weights exist for a folder's lists, `get_weighted_progress()` uses them instead of the equal-weight fallback.

**Password-gated writes**: both `POST` (set/change weights) and `DELETE /disciplines/folder/{folder_id}` (remove weights) require the header `X-Delete-Password`, checked with `secrets.compare_digest` against the same `settings.documents_delete_password` (a name inherited from the removed Documentações module; kept so existing `.env` files keep working) (403 if missing/wrong — see `_check_delete_password()` in `disciplines.py`). The desktop dashboard's weights modal (`saveDisciplineWeights()` in `app.js`) prompts for it via `prompt()` before calling `POST`. There's no UI wired to the `DELETE` endpoint yet, but it's gated the same way.

**Evolution curve** (`build_province_evolution`): reconstructs a temporal weighted-progress series from `date_closed` of each completed **task or subtask**. Used by `GET /dashboard/evolution` → `DashboardService.get_evolution_data()`. Each point is `{date: ISO, progress: float}` representing cumulative weighted progress at that moment. The series always starts at 0.0 (first task creation date) and ends with today's current value.

**The curve and the "Progresso por Província" bar chart must agree.** They are two views of the same number and are computed from the same inputs: the curve's `current_progress` comes from `compute_task_progress` (the same function behind `_weighted_completion_by_folder`), and the points decompose that total over time — each completed Activity adds `TASK_WEIGHTS_norm × SUBTASK_WEIGHTS_norm / n_lists` on the date it was closed, and a Discipline marked done closes whatever is left on its own date (it is worth 1.0 even with open Activities, per `compute_task_progress`). Until this was fixed, `get_folder_tasks_for_evolution` returned `"subtasks": []` for every task and the curve only counted **whole Disciplines closed** — so six provinces with real progress (HUAMBO, KUITO, LUBANGO, MALANJE, NDALATANDO, SUMBE: Activities done, no Discipline closed) rendered as a flat 0% line while the bar chart showed 2–3%, and even LUANDA diverged (84.18% vs 75.36%). If you ever change one of the two formulas, change both.

**`date_closed` is half-missing, so the curve falls back to `date_updated`** (`_closed_at()` in `cache_repository.py`): only 372 of 780 completed subtasks have the "Data de Conclusão" custom field filled in. Without the fallback those conclusions would produce no step at all. For roughly half the activities the step therefore sits on the last-edit date, not the declared completion date — the total is right, the exact day may not be.

## Civil Works Module (RDO)

**⚠ Temporarily disabled** via `RDO_MODULE_ENABLED=false` (default). While disabled: `main.py` does not register `civil.router`/`progress_civil.router` (all `/civil/*` and `/civil/progress/*` endpoints 404), `GET /rdo` and `GET /progresso-civil` return a 503 placeholder instead of rendering, and the "RDO Diário"/"Controle de Progresso" sidebar links are hidden (`{% if rdo_module_enabled %}` in `index.html`; `rdo.html`/`progress_civil.html` still contain their own copies of these links but those pages are unreachable while the flag is off). Set `RDO_MODULE_ENABLED=true` to restore full access — no code changes needed, the module itself was not touched.

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

**PDF export:** `generate_rdo_pdf(report_dict, site_name)` in `rdo_pdf_service.py`. Same `_s()` Latin-1 sanitizer and fpdf2 pattern as `report_service.py`. Leva o mesmo papel timbrado dos outros relatórios (ver "PDF Reports"); como o módulo está desligado, essa conversão **não foi conferida num PDF gerado** — vale olhar antes de reativar.

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

## Service Authorization Module (Autorização de Serviço)

Fluxo de pedido/aprovação para intervenções em campo ("preciso mexer no transmissor X pelo motivo Y").
Vive num **Space dedicado do ClickUp** (`Operações U2`, id `901314608766`), separado do
`CLICKUP_DEFAULT_SPACE_ID` — isso não é preferência, é requisito: dentro do space sincronizado, as
requisições entrariam no `cache_worker` (contaminando KPIs, donut de status, Gantt e todo PDF/XLSX,
porque `_leaf_tasks_clause()` conta qualquer tarefa-folha) e o `polling_worker` tentaria criá-las como
Tasks no Airbox.

**Fluxo completo:**
1. Funcionário preenche o **Form view** da lista `Autorizações de Serviço` (id `901329002275`) →
   ClickUp cria a tarefa em `Solicitado`. A lista tem só três statuses — `Solicitado`
   (not started, o inicial), `Autorizado` (done) e `Recusado` (closed); não há estado
   intermediário, a decisão é sempre em um passo.
2. Webhook `taskCreated` → `POST /webhooks/autorizacoes` (endpoint **separado** de `/webhooks/clickup`,
   que empurra tudo para o `SyncService`/Airbox e para o cache — nada disso se aplica aqui).
3. `AuthorizationService.handle_task_created` valida lista + status inicial, gera um **par de tokens**
   (`approve`/`reject`, `secrets.token_urlsafe(32)`, TTL `AUTHORIZATION_TOKEN_TTL_DAYS`) e envia um
   e-mail ao gestor com o resumo do pedido e dois botões.
4. O gestor clica → `GET /autorizacoes/decidir/{token}` só **mostra** a página de confirmação.
5. Confirmando → `POST` grava no ClickUp: status (`Autorizado`/`Recusado`), custom fields
   `Decidido Por` / `Data da Decisão` / `Observações da Decisão`, e um comentário com `notify_all`.
   O solicitante recebe e-mail de retorno (endereço lido do custom field `Solicitante`, tipo `users`).

**Três decisões de projeto que não podem ser desfeitas sem quebrar o módulo:**

- **GET nunca decide nada.** Clientes de e-mail e antivírus corporativos fazem *prefetch* de links; se
  o `GET` aplicasse a decisão, o scanner do Gmail autorizaria o serviço antes de o gestor ler o e-mail.
  A decisão só acontece no `POST` da página de confirmação.
- **A página de decisão responde com `Cache-Control: no-store`.** O `410` de token inválido é cacheável
  por padrão — sem o header, o navegador guarda o erro e continua mostrando "link inválido" mesmo
  depois de o link passar a valer (aconteceu em teste).
- **O backend renomeia a tarefa** (`build_task_name` → `<Equipamento> — <Site>`) antes de montar o
  e-mail. O ClickUp **não** tem template de nome no Form — só a pergunta "Task name", digitada pelo
  usuário, ou uma Automation `Change task name`, que dispara **depois** do nosso webhook e faria o
  e-mail sair com o nome antigo. Por isso a pergunta "Task name" deve ser removida do formulário.
  O rename é idempotente e, se falhar, o fluxo segue com o nome original.
- **Campos de data precisam de `value_options={"time": True}`** em `ClickUpClient.set_custom_field`.
  Sem isso o ClickUp trunca o valor para a meia-noite do fuso do workspace (a decisão das 08:44 UTC
  foi gravada como 03:00 UTC até isso ser corrigido).

**Token de uso único:** decidir consome o token *e* invalida o irmão (`AuthorizationRepository.consume`
marca `used_at` em todas as linhas da mesma `task_id`). Uma tentativa inválida — recusa sem motivo —
**não** queima o token: a validação (`validate_note`) roda antes de qualquer escrita.

**Setup (a API pública do ClickUp não cobre tudo):**
- `python scripts/setup_authorization_space.py` cria Space + Lista + os 12 custom fields
  (idempotente; o dropdown `Província` é populado a partir dos folders do space principal).
- **Statuses e Form view são manuais** — a API v2 não cria nem statuses customizados
  (`PUT /space/{id}` aceita o payload e ignora o campo `statuses`, devolvendo 200) nem views do tipo
  `form` (`POST /list/{id}/view` só aceita list/board/calendar/table/timeline/workload/activity/map/chat/gantt).
- `python scripts/register_authorization_webhook.py --url https://DOMINIO/webhooks/autorizacoes`
  registra o webhook (só `taskCreated`) e imprime o secret para o `.env`.
- `python scripts/check_authorization_setup.py` diagnostica o setup inteiro (env, space, lista,
  statuses, os 13 campos, form publicado + link, webhook) e lista o que falta. A única coisa que
  ele **não** consegue ver é quais campos foram arrastados para dentro do Form — a API não expõe
  a configuração da form view, só sua existência e o `public_url`.

**Campos da lista:** `Solicitante` (short_text), `E-mail` (email), `Província` (drop_down),
`Site / Estúdio`, `Equipamento`, `Tipo de Intervenção`, `Motivo`, `Data Prevista`,
`Duração Estimada (min)`, `Interrompe Transmissão`, mais os três de decisão preenchidos pelo backend.

`Solicitante` é texto e não `users` de propósito: o campo do tipo `users` rejeita quem não tem acesso
ao Space (erro `FIELD_129`) e não funciona bem em formulário público. Como consequência, o endereço do
funcionário vem do campo `E-mail` — `requester_email()` tenta, nesta ordem: custom field do tipo
`email` → campo de texto com "email" no nome e "@" no valor → campo `users` (formato antigo) →
`task["creator"]["email"]`. O fallback para o criador vale pouco num Form público e anônimo, onde o
criador é quem publicou o formulário: **se o campo `E-mail` sair do Form, o funcionário deixa de ser
notificado** (a decisão continua sendo gravada no ClickUp; a página avisa o gestor que ninguém foi
notificado).

A ordem de exibição no e-mail e na página vem de `_FIELD_ORDER` em `authorization_service.py` — o
ClickUp devolve os campos em ordem alfabética, péssima para leitura rápida. O casamento é por
**prefixo normalizado**, para o nome sobreviver a mudanças de unidade (`Duração Estimada (h)` virou
`(min)` sem quebrar nada). Campos novos criados no ClickUp aparecem no fim.

## Cronograma de Obra (Schedule Engine)

Substitui as planilhas PMEx (um ficheiro Excel por disciplina, com Cronograma/Gantt/Resumo/Parâmetros).
A lista "Site FM" de uma província passa a ser o cronograma: **editado só no ClickUp**, calculado pelo
backend. Ligado por `SCHEDULE_ENABLED` + `SCHEDULE_LIST_IDS`; listas fora dessa lista não são tocadas.

**Estrutura no ClickUp** — três níveis via subtarefas aninhadas (ClickApp *Nested Subtasks* tem de
estar ligado no space; sem ele a API devolve `ITEM_002 Cannot make subtasks of subtasks`):

```
Lista (Site FM)                 ← data de início da lista = dia 0 do projeto
  └─ Disciplina (Obra Civil, Logística, Área Técnica)
       └─ Grupo (Concrete Base for Generator…)
            └─ Tarefa           ← o que o utilizador edita
```

| Dado | Onde vive no ClickUp | Quem escreve |
|---|---|---|
| Duração, tipo (Útil/Corrido) | campos `Duração (dias)` (number) e `Calendário` (drop_down) | utilizador (folhas); motor nos resumos: **soma** das durações das tarefas dele (canceladas fora) |
| % concluído | campo `% Concluído` (manual_progress — barra nativa) | utilizador (folhas); motor (resumos) |
| Peso | campo `Peso (%)` (number): peso do item dentro do pai — ver "Peso (%)" | importador (planilhas de tipos de site); utilizador |
| Status | status nativo | os dois — ver regra abaixo |
| Antecessores | dependências nativas ("waiting on") | utilizador |
| Início / fim | `start_date` / `due_date` **nativos**: só o dia, ou com hora quando a lista tem jornada — ver "Jornada" | motor; o utilizador pode mexer numa folha — ver "Datas digitadas à mão" |
| Início fixado | campo `Início fixado` (date). Numa tarefa: "começa em" (vence as antecessoras). Num grupo/disciplina: o dia em que o bloco começa (vence as antecessoras de fora do bloco) | motor, quando alguém muda o início à mão (da tarefa ou do grupo); o utilizador apaga para soltar |
| Pausa | campos `Pausa de` / `Pausa até` (date) / `Motivo da pausa` (short_text) + `Histórico de pausas` (text) | utilizador (a pausa atual); motor (arquiva no histórico) — ver "Pausas" |
| Conclusão real | campo `Data de Conclusão` | utilizador, ou o motor (hoje) se vazio |
| Responsável | equipes (`group_assignees`): PROEF, U2BROADCAST, RNA | utilizador |
| Data de início do projeto | data de início da **primeira linha** (disciplina do topo), ou `start_date` da lista | utilizador; o motor copia a da primeira linha para a lista |
| Folga semanal | linha `folga=dom` na descrição da lista (padrão `SCHEDULE_WEEKEND_MASK`) | utilizador |
| Feriados | lista `SCHEDULE_HOLIDAYS_LIST_ID`: uma tarefa por feriado, data = vencimento | utilizador |

Os campos são criados **por lista** (a API v2 não cria campos a nível de Space), então cada lista tem
ids próprios — `schedule_fields.py` casa tudo por **nome**. Renomear um campo no ClickUp quebra a leitura.

**Motor** (`schedule_engine.py`, puro, sem ClickUp nem banco) — porta fiel da aba Cronograma: tudo é
calculado em *posição* (dias úteis desde o primeiro dia útil) e só depois vira data.
`compute_schedule(..., reschedule=False)` reproduz a planilha e é o que `test_schedule_engine.py` confere
contra `tests/fixtures/lubango_schedule.json` (51 tarefas, 11 resumos). Com `reschedule=True`:
- **concluída** → termina na data real e libera as sucessoras a partir dela;
- **em andamento** → o que falta (`duração × (1 − %)`) é executado a partir de hoje;
- **não iniciada** → nunca começa antes de hoje (uma tarefa atrasada desliza um dia por dia).

Dependência de/para um resumo é expandida para todas as folhas dele. "Corrido" converte por
`dias × dias_úteis_semana / 7` (cura de 14 dias = 12 úteis), como a planilha — um feriado dentro da
cura estica o prazo, limitação herdada. Os "marcos externos" (CIV-01, LOG-01…) não existem mais:
com tudo na mesma lista viraram dependências comuns (o importador faz essa conversão).

**% × status** (`reconcile_leaf`): 0% = aberto, 1–99% = fazendo, 100% = complete. Quando discordam,
vence o que o utilizador acabou de mexer — por isso existe a tabela `schedule_task_state` com o último
(%, concluída?) visto. Marcar complete leva o % a 100; baixar o % de uma concluída reabre; reabrir pelo
status tira o % de 100 (vira 99). Status fora do trio (impedimento, revisão) nunca é trocado. Os
resumos têm %, status, datas e duração **calculados** — editar um resumo à mão é desfeito no próximo
recálculo (exceto um status fora do trio, que é respeitado).

**Datas digitadas à mão** (numa tarefa-folha). `schedule_task_state` guarda também o início e o
término que o motor deixou em cada tarefa; uma data diferente foi mexida por alguém e vira **entrada**
do cálculo em vez de ser desfeita (`_typed_dates` detecta, `_interpret_edit` traduz):
- não iniciada: o início vira o campo **Início fixado** ("começa em" — `fixed_start` no motor) e o
  vencimento vira a **duração** que faz a tarefa terminar nesse dia, contada de onde ela
  começa — inclusive a meio de um dia, quando a antecessora termina a meio (durações de 0,25/0,5 e
  curas "Corrido" deixam frações): por isso a duração pode sair fracionada (ex.: 4,5). Em "Corrido",
  a duração em dias corridos que, convertida (× 6/7), termina nesse dia — também fracionada (ex.:
  17,5); antes saíam dias corridos inteiros e o fim caía um dia depois (fuzz de 2026-10-22). Mover as duas datas com a mesma distância entre elas é só mudar de lugar: a duração fica;
- em andamento: o início já valia como início real; o vencimento vira a duração cujo restante
  (`duração × (1 − %)`), contado de hoje, termina nesse dia (50% e 5 dias até o vencimento → 10;
  em "Corrido", convertido para dias corridos); vencimento antes de hoje é recusado com aviso. Uma
  tarefa aberta nunca termina antes de hoje (um marco sem duração "em andamento" terminava ontem);
- concluída: o vencimento vira a `Data de Conclusão`.
- `_interpret_edit` usa um cálculo prévio, sem as edições, para saber a posição exata (com a fração)
  de cada tarefa; as folhas fora do alcance da edição só são fixadas (`pinned`) se esse cálculo as
  moveria — fixar todas perdia a fração de dia e empurrava a sucessora meio dia (achado no teste real).
- **O estado vem do ClickUp:** cada tarefa gravada tem três leituras — o enviado, a resposta do PUT e a
  releitura da lista no fim (`_dates_after_writes`). Resposta diferente do enviado = o ClickUp guardou
  outra coisa, e é isso que fica (senão viraria "edição fantasma", visto no teste real de 2026-10-19).
  Resposta ou releitura com **uma só** das datas nova e a outra ainda a antiga = o ClickUp aplicou a
  gravação pela metade (visto no QA de 2026-10-22: o início não fica, o vencimento sim; causa não
  identificada, raro) — `_write_dates_again` regrava na hora. Releitura diferente de outro jeito =
  alguém mexeu depois do motor: o estado fica com o que o motor gravou e a execução seguinte trata a
  diferença como edição (antes era desfeita em silêncio).

Nessa execução **só a tarefa mexida e as que dependem dela** (`dependents_of`, com as dependências de
resumo expandidas) — mais os grupos e disciplinas que as contêm — têm as datas regravadas. As outras
folhas entram no motor com as datas de agora (`pinned`), e as sucessoras partem delas; o recálculo
seguinte sem edição volta a ser completo. **A data digitada vence a dependência** (decisão do
utilizador em 2026-10-22, como o "Must start on" do MS Project): uma tarefa com Início fixado começa
nesse dia mesmo antes de a antecessora terminar, e continua lá se a antecessora atrasar depois; o motor
deixa um **comentário de alerta** na tarefa. Só "hoje" ainda vence: numa tarefa não iniciada, um início
que já passou vira hoje (com comentário). As sucessoras dela seguem a partir dali. Apagar o Início
fixado devolve a tarefa às dependências. O campo é criado sozinho na primeira vez que for preciso (as
listas importadas antes não o têm) e faz parte do `FIELD_DEFS` do importador. Estado sem datas (de antes
deste recurso, ou tarefa nova) não conta como edição — o primeiro cálculo só registra as datas.

**Datas digitadas num grupo ou disciplina** (decisões de 2026-10-22). Antes eram desfeitas em silêncio
— era a maior parte dos "mudei a data e ela voltou" relatados. O estado guarda agora as datas de todos
os resumos, não só da primeira linha:
- **início** → grava o **Início fixado do próprio resumo**, que é **o dia em que o bloco começa**
  (decisão de 2026-10-23 — antes era só um piso, "não começar antes de"): no motor, cada tarefa do
  bloco parte dessa data (`fixed_start` do resumo; `_fixed_block` acha o grupo fixado mais interno
  acima dela) e as antecessoras **de fora** do bloco não a seguram; as de dentro continuam a valer, e as
  sucessoras do bloco partem do fim dele. Como numa tarefa: só "hoje" vence (data passada numa tarefa
  não iniciada → hoje, com comentário no grupo), o "Início fixado" de uma tarefa vence o do grupo, e
  o motor comenta no grupo quando ele começa antes do fim de uma antecessora de fora (alerta);
- o bloco **leva junto** o Início fixado das tarefas dele, deslocado pela mesma distância — senão uma
  tarefa fixada seguraria o bloco no lugar velho, ou perderia a vantagem que tinha sobre a antecessora;
- arrastar a barra do grupo (as duas datas com a mesma distância) = mudar o início;
- **vencimento** → desfeito, com comentário (o fim de um resumo vem das tarefas dele);
- **primeira linha**: o início dela continua a ser o início do projeto. Como é um resumo, com uma tarefa
  iniciada ou concluída antes ela continua a mostrar essa data — o motor comenta na linha que o início
  do projeto mudou. Mudar o início do projeto também leva junto, pela mesma distância, todos os "começa
  em" das tarefas e os "Início fixado" dos grupos — senão ficavam sozinhos no lugar velho. A "primeira linha" é a disciplina **criada primeiro**: numa lista **duplicada** no
  ClickUp a ordem de criação pode sair outra (no space "PEMx - RNA (Teste 2)" é a Logística).

**Proteções contra quem mexe durante uma execução** (QA de 2026-10-22):
- antes de cada lote de `_CHECK_EVERY` gravações, `_changed_since` pergunta ao ClickUp
  (`get_tasks(date_updated_gt=…)`) o que mudou desde a leitura; tarefa que alguém mexeu entretanto não é
  regravada — fica para a execução seguinte, que o webhook dessa edição dispara. Antes, editar uma
  tarefa poucos segundos depois de outra (enquanto o motor gravava as dependentes) era desfeito;
- **estado velho** (banco restaurado de backup, estado que não chegou a ser salvo): mais de
  `_MAX_EDITS_PER_RUN` datas diferentes do estado guardado numa execução não é uma pessoa — com "a data
  digitada vence a dependência", isso criaria dezenas de "começa em" falsos (aconteceu no QA). As datas
  guardadas são descartadas, a execução só recalcula e regista, e sai um aviso. **Nunca rodar o motor
  contra as listas de produção com outro banco** (um `dry_run` não grava nada e é seguro);
- erro 5xx do ClickUp é tentado de novo (`_call`), como o 429 — perdia-se a execução inteira.
- **Fuso:** as datas são lidas no fuso da obra (`ms_to_site_date`, `SCHEDULE_UTC_OFFSET_HOURS`): uma
  data escolhida no ClickUp sem hora chega como a meia-noite de quem digitou, e a meia-noite de Angola em
  UTC já é o dia anterior. A data digitada é regravada pelo motor para a dashboard, que lê em UTC,
  mostrar o mesmo dia: o ClickUp guarda data sem hora como a meia-noite do fuso de quem grava (o token
  da app: 03:00 UTC, conferido em 2026-10-15), não o instante enviado.
- **Limitação:** sobra uma janela de ~1 s (entre a checagem e o PUT de um lote) em que uma data
  digitada pode ser sobrescrita sem virar edição.
- **Log:** cada execução com edições regista o que cada data virou (`_Edit.describe`) — antes só havia a
  contagem, e reconstruir um "a data voltou" a partir do log era impossível.

**Sem laço de webhook**: `ScheduleService.recalculate` grava só as diferenças. As gravações disparam
webhooks, que agendam outro recálculo, que não encontra nada para gravar. Qualquer campo novo
gravado pelo motor tem de convergir (comparar o que se lê com o que se gravaria) — senão vira laço.

**Gatilhos** (`schedule_worker.py`): webhook de qualquer tarefa da lista → espera
`SCHEDULE_DEBOUNCE_SECONDS` (5 s; reinicia a cada novo evento) → recalcula — uma execução por lista de
cada vez (lock por lista em `run_recalculation`; um aviso que chega durante o cálculo espera e roda
depois); e um job a cada
`SCHEDULE_INTERVAL_SECONDS`. O job periódico não é redundância: o ClickUp **não envia webhook quando
uma dependência é removida** (criar envia `taskUpdated` nas duas tarefas) nem quando a lista de
feriados muda. `POST /schedule/{list_id}/recalculate?dry_run=true` mostra o que mudaria sem gravar.

**Pré-requisitos no space (manuais, verificados em 2026-10-08):** *Nested Subtasks* ligado e
*Reschedule Dependencies* **desligado** — ligado, o ClickUp move sozinho as tarefas dependentes com
regras próprias (sem feriados nem sábado útil) e briga com o motor. **Em 2026-10-22 a API mostrava
`remap_dependency_settings: enabled` no space de produção** (e no Teste 2): gravações pela API não
disparam o reagendamento (testado), mas pela tela não deu para testar — conferir em ClickApps.
**Automação do ClickUp:** há uma que grava `Data de Conclusão` = hoje quando o status vira concluído
(veio na cópia do space; quase certamente existe em produção) — ela sobrescreve uma data real
preenchida **antes** de concluir. O motor já põe hoje quando o campo está vazio, então a automação é
redundante; para registar uma data real, preencher o campo **depois** de concluir (ou mudar o
vencimento da tarefa concluída). Todo membro de uma equipe precisa
ter acesso à lista, senão o ClickUp recusa a atribuição (`ACCESS_200`).

**Dashboard**: o cache guarda `progress_pct` / `duration_days` / `calendar_type`
(`progress_pct` não nulo é o que marca uma tarefa de cronograma). Nessas, `due_date` vem da data
nativa (fim do dia), não do campo "Vencimento". `_build_schedule_tree` achata os 3 níveis para o
formato de 2 que `weights_config.py` espera, com `weight` (duração útil) e `progress` (0..1) explícitos
em cada folha — é isso que faz o progresso da lista ser ponderado por duração em vez dos pesos por nome.
As listas que não são de cronograma seguem exatamente como antes. Dentro da província cada lista
continua valendo igual (Site FM e Estudios 50/50, salvo `discipline_weights`).

**Dependências na dashboard**: `upsert_task` guarda em `depends_on_json` os ids de que a tarefa
depende (só o lado que espera — o ClickUp devolve o mesmo registo nas duas tarefas do par).
`_DependencyIndex` (`dashboard_service.py`) monta `depends_on` e `blocks` para exibição; num grupo
entram só as dependências que cruzam a fronteira do grupo. Como a remoção de uma dependência não
gera webhook, ela só some do cache no refresh seguinte.

**Relatórios**: lista de cronograma (`_is_schedule` em `report_service.py` — alguma tarefa com
`progress_pct`) usa a tabela `_render_schedule_rows` em vez das tabelas de 2 níveis: nome indentado
por nível, duração, início, término, barra de %, status e equipe. Vale para o detalhe da lista no
relatório de província (PDF e XLSX) e para os relatórios de lista e de disciplina, que ganham também
uma linha de resumo no cabeçalho (% ponderado por duração e intervalo de datas). Lista sem data de
início sai com as colunas de data em branco. As listas comuns continuam com o layout antigo.
- **Listagens** (`_listing_tasks_clause`: em atraso e próximas entregas, por pasta e por space — as
  do space também alimentam a dashboard e o assistente): tarefa de topo nas listas comuns,
  **tarefa-folha** nas de cronograma, com o grupo no nome (`"Grupo / Tarefa"`). O topo ali é um
  resumo cujo prazo é o fim da disciplina inteira.
- **Diário/semanal** (`get_period_updates`): só a tarefa-folha conta como atualização. Disciplina e
  grupo têm status e datas regravados pelo motor a cada recálculo e apareceriam todo dia; a
  disciplina entra só como contêiner e o grupo vai no nome. Tarefa em andamento mostra o % ao lado
  do status (`fazendo 40%`).

Como o motor reprograma, **uma tarefa de cronograma quase nunca aparece "em atraso"**: o atraso
aparece como a data de fim do projeto a andar. Quem mede isso é a linha de base.

**Linha de base** (tabela `schedule_baseline`: início e término planeados por tarefa). É gravada
sozinha no **primeiro cálculo real** de uma lista — o plano puro (`compute_schedule(reschedule=False)`
sobre as tarefas sem %, início nem conclusão), não o andamento — e depois não muda. Os "Início fixado" que já
existem nesse primeiro cálculo **entram** no plano (2026-10-23): o gerente fixa as datas obrigatórias e só
depois põe o início do projeto, e essas datas são plano, não desvio; as fixadas depois contam como desvio. Um `dry_run` não
grava. `POST /schedule/{list_id}/baseline` (senha `X-Delete-Password`) **redefine**: adota o cronograma
atual (com a reprogramação) como o novo plano, sem escrever nada no ClickUp; na dashboard é o botão
"Redefinir linha de base" da lista. Vive no SQLite da app, não no ClickUp — apagar o `sync.db` perde o
plano e o próximo cálculo grava um novo a partir do estado daquele momento.
- **Desvio** = término atual − término da linha de base, em dias corridos (positivo = atrasada).
  `CacheRepository.get_schedule_deviation` compara o maior prazo das tarefas de cronograma em cache com
  o maior término da linha de base; entra em `get_lists_with_metrics`, `get_list_kpis` e
  `get_folders_with_metrics` (a província fica com o pior desvio das suas listas) como
  `schedule_finish` / `baseline_finish` / `delay_days` — chaves **ausentes** quando não há linha de base.
- Cada tarefa leva `baseline_due` / `delay_days` (`TaskSummary`); tarefa criada depois da linha de base
  não tem desvio até alguém redefinir.
- **Na tela**: o selo da província (`healthStatus` em `app.js`, `healthColor` no mobile) é o desvio
  ("Atrasada 6 d", "Adiantada 2 d", "No prazo"); sem linha de base só descreve o andamento ("Não
  iniciada", "Em andamento", "Concluída") — o antigo "Atenção" para toda província a 0% saiu. O cartão
  "Províncias em Atraso" da visão geral e a coluna "Desvio" da lista vêm do mesmo número.

**Importar uma província:** `python scripts/import_schedule.py civil.xlsx logistica.xlsx tecnica.xlsx
--list-id <id> --replace "Site FM" --holidays-list-id <id> --recalculate --yes` (sem `--yes` é ensaio).
`--replace` apaga todas as tarefas da lista antes e exige o nome exato dela como confirmação.

Cada província tem a sua planilha e elas diferem ("Torre existentes" = 62 linhas; "Torres Novas" = 71,
com fundação e montagem de torre) — importar sempre a da própria província. O importador também:
- cria as vistas "Cronograma" e "Gantt" (campos criados pela API não entram sozinhos em nenhuma vista,
  e sem elas a lista parece vazia) e manda `null` para os outros dropdowns da lista, senão o ClickUp
  preenche cada um com a primeira opção (foi assim que "Disciplinas" virou "CIVIL" em tudo);
- `--zero` importa com todo o progresso em 0%; `--start-date` / `--no-start-date` sobrepõem a data da planilha.

**Início pela primeira linha** (`_project_start`): pôr a data de início na primeira linha da lista (a
disciplina **criada primeiro** — a primeira da planilha na importação, `_top_task_id` por `date_created`)
dá a partida no projeto. **Não usar o `orderindex`:** o ClickUp muda esse número quando uma tarefa é
editada, e a "primeira linha" passava a ser outra a cada gravação. Pôr a data: o motor grava essa
data como início da lista e calcula todas as tarefas a partir dela, pela duração e pelas dependências.
Mudá-la depois move o projeto **inteiro** (todas as cadeias, sem a restrição de "só as dependentes"). A
data é reconhecida como digitada pela mesma regra das folhas (diferente da que o motor deixou nela — o
estado da primeira linha também é guardado); sem isso vale o início da lista, que continua a funcionar
pelas configurações da lista (essa mudança não gera webhook: entra no recálculo periódico). As outras
disciplinas e grupos continuam calculados. Início no passado: as tarefas não iniciadas começam hoje (aviso).
Tarefas concluídas e em andamento não andam com o início do projeto (têm datas reais); se a primeira
linha já tem tarefas feitas, o início que ela mostra volta a ser o real — o do projeto fica na lista.
Dependências entre subtarefas de tarefas e disciplinas diferentes da mesma lista valem sempre (ex.: o
rack da Área Técnica espera a concretagem da Obra Civil); dependência para outra lista é ignorada com aviso.

**Peso (%)** (planilhas de tipos de site, 2026-10-23, decisão do utilizador: "o peso manda no %").
Cada linha pode ter o peso dela dentro do pai (os de um mesmo pai somam 100 nas planilhas). Quando
**todos** os filhos ativos de um resumo têm peso, o % do resumo é a média ponderada por ele — nível a
nível, como a coluna "% Complete" da planilha; senão continua pela duração útil das tarefas-folha,
como sempre foi (as listas antigas, sem o campo, não mudam). Vale nos três lugares, que têm de dar o
mesmo número:
- **motor** (`compute_schedule`, resumos do mais fundo para o topo; `overall_percent` para a lista) —
  é o % que vai para o ClickUp;
- **dashboard e relatórios** (`_build_schedule_tree`): com peso em todas as linhas de topo, cada uma
  pesa pelo seu `Peso (%)` e as folhas de dentro levam o **peso efetivo** (produto dos pesos do caminho,
  normalizados em cada nível) — dá exatamente a média nível a nível; o cache guarda o campo em
  `clickup_task_cache.weight_pct`;
- conferido no ClickUp real (lista "Prova Tipo 2 (peso)" no Teste 2): 3,75% no motor e na dashboard.

**Planilhas de tipos de site de transmissão** (`schedule_xlsx_sitetype.py`, escolhido por `load_schedule`
quando há uma aba "Site FM - Type N"): os 4 modelos da pasta "Tipos de Sites Transmissão" — 1 torre e
abrigo existentes, 2 torre nova e abrigo existente, 3 green field, 4 torre existente sem abrigo — e a
"Transmitter Type of Site List" diz o tipo de cada província. A WBS (ID, tipo Project/Stage/Task, nível,
pai) vira disciplina (Stage nível 2) → grupo (Stage nível 3) → tarefa; a linha "Project" é a própria
lista; "Acceptance & Handover" é uma tarefa de topo sem filhos. As datas por etapa ("Stage Start") ficam
de fora a pedido do utilizador (só a estrutura); "Resource Names" só vira equipe sem `--no-teams`.
**Ordem das etapas — cadeia** (decisão de 2026-10-23): na planilha as etapas não têm antecessoras
entre si; a ordem está só nas datas de "Stage Start", digitadas à mão. Ignorá-las punha as seis etapas a
começar juntas (o "Acceptance & Handover" de Huambo caía no 3.º dia). Cada etapa passa a **depender da
etapa anterior** na planilha quando esta começou antes (Logistics → Electrical → Equipment →
Pre-Commissioning → SAT; Obra Civil e Logística começam juntas e ficam em paralelo). Para uma etapa
começar num dia certo (as esperas que a planilha tinha, ex.: Equipment Installation só em 10/11),
preenche-se o **"Início fixado"** dela, que é definitivo. Houve um campo "Início após (dias úteis)" com a
distância do "Stage Start" ao início do projeto; saiu no mesmo dia, a pedido do utilizador, para ficar só
o "Início fixado" — a API não apaga campos, então nas 14 listas do Teste 2 ele ficou vazio e fora da vista.
Aplicadas ao Site FM das 14 províncias da lista no space "PEMx - RNA (Teste 2)" (`--zero --no-teams`,
sem data de início); Mbanza Congo e Ndalatando não estão na lista.

**Jornada — datas com hora** (decisão de 2026-10-23). Uma lista com a linha `jornada=08:00-17:00` na
descrição (e, opcional, `almoço=12:00-13:00`) recebe início e fim **com hora**: o motor converte a fração
de dia da posição em relógio (`clock_time` em `schedule_engine.py`; `parse_workday` em
`schedule_fields.py`) — uma tarefa de 0,25 dia que começa no início do dia vai das 08:00 às 10:00, e o
almoço é saltado (um início que cairia às 12:00 vai para as 13:00; um fim às 12:00 fica). A hora é a da
obra (`SCHEDULE_UTC_OFFSET_HOURS`); o ClickUp mostra-a no fuso de cada utilizador — no Brasil, 08:00 de
Angola aparece como 04:00. Gravada com `start_date_time`/`due_date_time` = true e comparada pelo ms exato
(`_date_changes` com `stamp`); as datas digitadas continuam a ser reconhecidas **pelo dia** (mudar só a
hora de uma tarefa não é edição — o motor repõe a hora). Sem a linha, tudo como antes (só o dia). O
importador põe a linha a partir da aba Parameters das planilhas de tipos de site (`list_lines`).

**Colunas da planilha que vêm para o ClickUp** (`SITE_TYPE_FIELD_DEFS`, criadas pelo importador só nas
planilhas de tipos de site; o motor preenche as calculadas **só se a lista tiver o campo**):
- `ID` (number) e `WBS` (short_text) — o ID da linha na planilha e o **nível no ClickUp**: `1` etapa ou
  tarefa de topo, `2` grupo, `3` tarefa (o "WBS Level" da planilha menos 1, já que a linha do projeto é a
  própria lista; decisão de 2026-10-23 — antes era um código `1.2.3`). Gravados pelo importador; o motor
  não mexe neles.
- `Peso no projeto (%)` — o peso efetivo da linha no projeto inteiro (`project_weights`: produto dos
  pesos normalizados do caminho × 100), a coluna "Project Weight (%)" da planilha.
- `% Planejado` — quanto já devia estar feito no início de hoje segundo a **linha de base** (linear
  entre o início e o fim planeados, em dias úteis; resumos por `rollup`, a mesma regra de peso/duração
  do %). Sem linha de base fica em branco.
- `Situação` (drop_down): Concluída, Pausada (pausa atual), Em andamento, Atrasada (% real abaixo do
  planejado), Não iniciada.
- `Dias pausados` — dias úteis parados: o histórico mais a pausa atual até hoje; nos resumos, a soma.
- `Motivo da pausa` passa a ser **lista fechada** (Logística, Clima, Externo, Outro) nas listas novas; o
  motor lê tanto a lista quanto o texto antigo (`read_option`). A API **não apaga campos** (`DELETE
  /field` → 405): uma lista que já tinha o motivo em texto fica com ele — o importador não cria um
  homónimo.
- Na vista "Cronograma", ID e WBS entram à frente e os outros no fim (`add_view_columns`).
- Todos convergem (comparação com tolerância de 0,005 nos números, opção pelo nome no drop_down), então
  não criam laço de webhook.

**Duração dos resumos** = soma das durações das tarefas dele, como digitadas (tarefas em paralelo somam
por inteiro; canceladas não entram). Antes era a amplitude em dias úteis; o peso no progresso continua
a ser a duração útil de cada folha.

**Pausas** (`schedule_pauses.py`): parar uma subtarefa — ou uma tarefa/disciplina inteira, que vale
para todas as tarefas abaixo dela — é preencher **Pausa de** (e o motivo); retomar é preencher **Pausa
até**. Em branco, "Pausa até" = parada até nova ordem (vai até hoje e anda com ele). Os dias de pausa
não contam como trabalho (`pauses` no `ScheduleTask`, `_work_through` no motor): a duração fica, o fim
se afasta, começar dentro da pausa é começar quando ela acaba, e o que falta de uma tarefa em andamento
é feito depois dela. Só a tarefa pausada e as que dependem dela andam (a assinatura das pausas vai para
`schedule_task_state.pause`; mudou = raiz do recálculo, como uma data digitada).
- **Histórico:** no dia seguinte ao "Pausa até", o motor acrescenta a pausa no campo de texto
  **Histórico de pausas** (`dd/mm/aaaa – dd/mm/aaaa · motivo`, uma por linha) e limpa os três campos — ficam
  livres para a próxima. Pausa que encosta numa arquivada (sobrepõe, começa no dia seguinte ou só há folga
  entre elas) vira uma só, com os motivos juntos. O histórico pode ser editado à mão; linha que não se lê
  fica como está e gera aviso. Apagar as datas de uma pausa que ainda não terminou = cancelar (não arquiva).
  As pausas do histórico não entram no cálculo (as datas reais já as contêm): servem para o Gantt.
- **Gantt:** toda pausa (histórico + atual) é uma faixa **zebrada vermelho/branco** — PDF (`_zebra`, listras
  a 45° recortadas com `rect_clip`), XLSX (preenchimento nativo `darkUp`, com comentário do motivo) e
  dashboard (`PAUSE_ZEBRA` em `charts.js`, só na fatia dos dias parados dentro da coluna da semana; motivo no
  tooltip). A pausa da própria tarefa aparece onde estiver, inclusive antes da barra (explica o atraso); a
  herdada da tarefa-mãe só no trecho da barra de cada filha. O cache guarda as pausas em
  `clickup_task_cache.pauses_json`. O Gantt nativo do ClickUp não tem zebra — lá só a barra fica mais comprida.
- **Campos por lista:** fazem parte do `FIELD_DEFS` do importador; nas listas já importadas são criados pela
  implantação (`ensure_fields` + `add_view_columns`, que também põe as colunas na vista "Cronograma" sem
  mexer em filtros/agrupamento). Lista sem os quatro campos ignora pausas.

**Sem data de início, sem datas.** Planilha sem data de início → a lista fica sem `start_date`, o motor
recusa calcular ("lista sem data de início") e as tarefas ficam sem datas até alguém preencher o início
da primeira linha (ou da lista) no ClickUp. A API não aceita `null` para limpar o `start_date` de uma lista; aceita `0`, que
`ms_to_date` trata como ausente (não como 01/01/1970).

**Estúdios têm outro formato de planilha** (`schedule_xlsx_studio.py`, escolhido sozinho por
`load_schedule` quando o ficheiro não tem a aba "Parâmetros" e tem STUDIO/CTP/NEWSROOM): dois ficheiros
por província (Obra Civil e Área Técnica), uma aba por sala, tabela estilo MS Project com até 4 níveis,
semana de segunda a sexta (`folga=sab, dom` na lista) e feriados em `STUDIO!L4:L10`. No ClickUp **cada sala
é uma lista** da pasta da província — **STUDIO, CTP e NEWSROOM** (`--room` no importador; nenhuma dependência
atravessa salas) — com o mesmo padrão dos sites: **disciplina (o ficheiro) → grupo → tarefa**. O grupo é o
resumo mais fundo acima das tarefas, as fases que só agrupam resumos ("Civil Works", "Technical Center") são
achatadas, a linha de projeto e os marcos de
duração zero ("Fim da Obra Civil", "End of Work") não viram tarefas, e cada "Marco externo — Obra Civil
concluída: <tarefa>" da Área Técnica vira dependência da tarefa da Obra Civil com esse nome, na mesma
sala. O leitor recusa a planilha se a coluna Antecessores não bater com as linhas que a fórmula de Início
usa. Todas as planilhas de estúdio vieram com a mesma data de início (19/10/2026, modelo) e foram
importadas sem data (`--no-start-date`), como os sites sem data.

**Marco externo sem origem vira tarefa.** Um marco da coluna J que nenhum ficheiro fornece mas está
declarado na aba Parâmetros (ex.: Saurimo, `EXT-01` "Torre entregue no site") é criado por
`schedule_xlsx.py` como tarefa própria, logo antes de quem depende dela, sem duração nem equipe —
preenche-se a duração no ClickUp com o prazo de entrega.

## Agreement ↔ List Matching

Lists and agreements are matched **by name** (case-insensitive). If names don't match:
1. Check existing mappings: `GET /sync/mappings/agreements`
2. Create manual mapping: `POST /sync/mappings/agreements` (body: `clickup_list_id`, `clickup_list_name`, `airbox_agreement_id`)

## Database

SQLite (`sync.db`), both locally and in production. No Postgres — schema is auto-created at startup via `Base.metadata.create_all`, which only creates missing tables, it never alters existing ones (no migrations); `alembic` is listed in `requirements.txt` but is not used.

**New columns on existing tables are added automatically at startup**: `init_db()` (`src/core/database.py`) runs `create_all` and then `_sync_missing_columns()`, a lightweight self-migration for SQLite — it inspects every table already in `Base.metadata`, diffs its real columns against what the ORM model declares, and issues `ALTER TABLE ... ADD COLUMN` for anything missing (SQLite supports this as long as the column is nullable or has a default; existing rows just get `NULL`/the default for the new column). This means adding a plain nullable column to a model (e.g. `observacoes` on `ClickUpTaskCache`) just works on the next deploy/restart — **no manual `ALTER TABLE` or file deletion needed**. It does *not* handle renaming/dropping columns, changing a column's type, or adding a `NOT NULL` column with no default (those still require deleting `sync.db`/`dev.db` to recreate, losing all cached data, or a manual migration).

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

**Authorization table** (in `authorization_models.py`, imported in `main.py`):
- `authorization_token` — par de tokens por requisição (`task_id`, `action`, `token`, `expires_at`, `used_at`, `used_note`). Consumir um marca os dois como usados.

**Schedule table** (in `schedule_models.py`, imported in `main.py`):
- `schedule_task_state` — último (%, concluída?, início, término) que o motor deixou por tarefa; decide quem vence quando % e status discordam e reconhece uma data digitada à mão
- `schedule_baseline` — linha de base: início e término planeados por tarefa (ver "Linha de base")

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
| `RDO_MODULE_ENABLED` | Feature flag for RDO Diário + Controle de Progresso (temporarily disabled — see Civil Works Module section). Set `true` to re-enable | `false` |
| `DOCUMENTS_DELETE_PASSWORD` | Shared password (header `X-Delete-Password`) for the admin writes: discipline weights and schedule baseline/recalculate. Name inherited from the removed Documentações module | `u2dashboard2026` |
| `EMAIL_ENABLED` | Ativar envio automático de relatório semanal por email | `false` |
| `EMAIL_SMTP_HOST` | Servidor SMTP | `smtp.gmail.com` |
| `EMAIL_SMTP_PORT` | Porta SMTP (STARTTLS) | `587` |
| `EMAIL_USER` | Conta Gmail do remetente | `""` |
| `EMAIL_PASSWORD` | App Password do Google (não a senha normal da conta) | `""` |
| `EMAIL_FROM` | Nome e email do remetente (ex: `U2 Broadcast Angola <email@gmail.com>`) | `""` |
| `EMAIL_RECIPIENTS` | Destinatários separados por vírgula | `""` |
| `EMAIL_REPORT_WEEKDAY` | Dia da semana do envio (0=segunda … 6=domingo) | `6` |
| `EMAIL_REPORT_HOUR` | Hora UTC do envio | `8` |
| `AUTHORIZATION_MODULE_ENABLED` | Liga o módulo de Autorização de Serviço (rotas + webhook) | `false` |
| `AUTHORIZATION_SPACE_ID` | Space dedicado das autorizações (NUNCA o space sincronizado) | `""` |
| `AUTHORIZATION_LIST_ID` | Lista das requisições; tarefas de outras listas são ignoradas | `""` |
| `AUTHORIZATION_WEBHOOK_SECRET` | HMAC do webhook de autorizações; vazio = pula verificação | `""` |
| `AUTHORIZATION_APPROVER_EMAIL` | Gestor que recebe e decide os pedidos | `""` |
| `AUTHORIZATION_APPROVER_NAME` | Nome gravado em `Decidido Por` e no comentário | `Gestor` |
| `AUTHORIZATION_TOKEN_TTL_DAYS` | Validade dos links de decisão | `7` |
| `AUTHORIZATION_PUBLIC_BASE_URL` | URL pública da app — monta os links do e-mail | `""` |
| `AUTHORIZATION_STATUS_PENDING` | Status inicial que dispara a notificação | `Solicitado` |
| `AUTHORIZATION_STATUS_APPROVED` | Status gravado ao autorizar | `Autorizado` |
| `AUTHORIZATION_STATUS_REJECTED` | Status gravado ao recusar | `Recusado` |
| `SCHEDULE_ENABLED` | Liga o motor do cronograma (worker, webhook, rota `/schedule`) | `false` |
| `SCHEDULE_LIST_IDS` | Listas geridas pelo motor, separadas por vírgula | `""` |
| `SCHEDULE_HOLIDAYS_LIST_ID` | Lista de feriados (fora do space sincronizado) | `""` |
| `SCHEDULE_WEEKEND_MASK` | Folga semanal padrão, Seg→Dom, `1` = folga | `0000001` |
| `SCHEDULE_DEBOUNCE_SECONDS` | Espera após webhook antes de recalcular | `5` |
| `SCHEDULE_INTERVAL_SECONDS` | Intervalo do recálculo periódico | `300` |
| `SCHEDULE_UTC_OFFSET_HOURS` | Fuso da obra (define "hoje" para o motor); Angola = 1 | `1` |
| `EMBED_ALLOWED_ORIGINS` | Origens que podem abrir a app num iframe (Nextcloud), separadas por vírgula; vazio = sem restrição | `""` |
| `NEXTCLOUD_JWT_PUBLIC_KEY_PEM` | Chave pública (PEM) que confere o JWT do External sites; vazio = identificação desligada | `""` |
| `NEXTCLOUD_JWT_ISSUER` | Opcional: URL base do Nextcloud; token com outro `iss` é recusado | `""` |

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
- `test_authorization_service.py` — formatação de custom fields, ordem do resumo, validação do motivo
- `test_authorization_flow.py` — ciclo dos tokens e decisão ponta a ponta com ClickUp/SMTP dublados
- `test_schedule_engine.py` — motor do cronograma: paridade com as planilhas, calendário, reprogramação, % × status, Início fixado, datas fixadas e dependentes
- `test_schedule_service.py` — leitura/gravação contra um ClickUp em memória (segunda execução não grava nada), datas digitadas à mão (atraso, adiantamento, mover, conflito com a antecessora, só as dependentes mudam, fuso), início pela primeira linha e dependências entre disciplinas
- `test_schedule_service.py` também cobre (QA de 2026-10-22): `TestSummaryEdits` (grupo movido, vencimento de grupo, bloco leva os "começa em"), `TestWritesRacingWithPeople` (edição durante a gravação, gravação pela metade, checagem por lotes), `TestStaleState` (estado velho) e a retentativa em 5xx
- `test_schedule_pauses.py` — pausas: histórico (leitura/escrita), arquivamento com junção de pausas contíguas e o efeito no motor
- `test_i18n.py` — versão em inglês: script de termos, nomes do ClickUp traduzidos e idioma do assistente
- `test_embed_security.py` — cabeçalho `frame-ancestors` (com e sem configuração, e em resposta de streaming)
- `test_nextcloud_auth.py` — JWT do Nextcloud: assinatura ES256, expiração, emissor, confusão de algoritmo, formatos da chave e `GET /auth/me`
- `test_schedule_cache.py` — cache, progresso ponderado por duração e telas com 3 níveis
- `test_schedule_reports.py` — relatórios (PDF/XLSX), listagens, diário/semanal e Gantt de província sobre a lista de 3 níveis
- `test_schedule_xlsx_sitetype.py` — leitor das planilhas de tipos de site: 3 níveis a partir da WBS, pesos em %, datas fora, 5º nível recusado, ID/WBS e a jornada
- `test_schedule_fields_info.py` — leitura da jornada na descrição e dos campos drop_down (opção por nome/orderindex)
- `test_schedule_xlsx_studio.py` — leitor das planilhas de estúdio: uma lista por sala, disciplina → grupo → tarefa, fases achatadas, marcos externos virando dependências, conferência fórmula × Antecessores

Unit tests:
- `test_civil_progress.py` — pure EVM calculation functions from `progress_service.py` (pct, contribution, site/global progress)
- `test_rdo_feeds_progress.py` — verifies that creating a RDO with `activity_def_id` automatically upserts measurements

Integration tests:
- `test_webhook_cache_update.py` — full webhook → cache → SSE path against a real in-memory DB
- `test_dashboard_endpoints.py` — `/dashboard/*` endpoint responses with seeded cache data

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
