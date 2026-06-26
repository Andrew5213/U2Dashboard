from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.core.database import init_db
from src.core.logging import setup_logging
from src.core.config import settings
from src.api import health, webhooks, sync
from src.api import dashboard, dashboard_stream, reports, disciplines, chat
from src.workers.polling_worker import start_polling, stop_polling
from src.workers.cache_worker import start_cache_worker, stop_cache_worker
# Garante que os modelos de cache sejam criados pelo init_db
import src.models.cache_models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()

    if settings.clickup_default_space_id:
        start_polling(settings.clickup_default_space_id)

    if settings.dashboard_enabled and settings.clickup_default_space_id:
        start_cache_worker(settings.clickup_default_space_id)

    yield

    stop_cache_worker()
    stop_polling()


app = FastAPI(
    title="ClickUp ↔ AltoQI Visus Integration API",
    description="Middleware bidirecional entre ClickUp e AltoQI Visus Workflow",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")
app.mount("/img", StaticFiles(directory="src/img"), name="img")
templates = Jinja2Templates(directory="src/templates")

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(sync.router)
app.include_router(dashboard.router)
app.include_router(dashboard_stream.router)
app.include_router(reports.router)
app.include_router(disciplines.router)
app.include_router(chat.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    chat_enabled = settings.chat_enabled and bool(settings.anthropic_api_key)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"chat_enabled": chat_enabled},
    )


@app.get("/assistente", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not (settings.chat_enabled and settings.anthropic_api_key):
        return HTMLResponse("<h2>Assistente de IA desabilitado.</h2>", status_code=503)
    return templates.TemplateResponse(request=request, name="chat.html")
