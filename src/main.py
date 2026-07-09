import os
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
from src.api import civil, progress_civil
from src.workers.polling_worker import start_polling, stop_polling
from src.workers.cache_worker import start_cache_worker, stop_cache_worker
from src.workers.email_worker import start_email_worker, stop_email_worker
# Garante que os modelos sejam criados pelo init_db
import src.models.cache_models  # noqa: F401
import src.models.civil_models  # noqa: F401
import src.models.progress_models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()

    if settings.clickup_default_space_id:
        start_polling(settings.clickup_default_space_id)

    if settings.dashboard_enabled and settings.clickup_default_space_id:
        start_cache_worker(settings.clickup_default_space_id)

    if settings.email_enabled and settings.clickup_default_space_id and settings.email_user:
        start_email_worker(settings.clickup_default_space_id)

    yield

    stop_email_worker()
    stop_cache_worker()
    stop_polling()


app = FastAPI(
    title="ClickUp ↔ AltoQI Visus Integration API",
    description="Middleware bidirecional entre ClickUp e AltoQI Visus Workflow",
    version="1.0.0",
    lifespan=lifespan,
)

os.makedirs(settings.civil_uploads_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory="src/static"), name="static")
app.mount("/img", StaticFiles(directory="src/img"), name="img")
app.mount("/uploads", StaticFiles(directory=settings.civil_uploads_dir), name="uploads")
templates = Jinja2Templates(directory="src/templates")

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(sync.router)
app.include_router(dashboard.router)
app.include_router(dashboard_stream.router)
app.include_router(reports.router)
app.include_router(disciplines.router)
app.include_router(chat.router)
app.include_router(civil.router)
app.include_router(progress_civil.router)


_MOBILE_UA_KEYWORDS = ("mobile", "android", "iphone", "ipad", "ipod")


def _is_mobile(request: Request) -> bool:
    view = request.query_params.get("view", "").lower()
    if view == "desktop":
        return False
    if view == "mobile":
        return True
    ua = request.headers.get("user-agent", "").lower()
    return any(kw in ua for kw in _MOBILE_UA_KEYWORDS)


@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    chat_enabled = settings.chat_enabled and bool(settings.anthropic_api_key)
    template = "index_mobile.html" if _is_mobile(request) else "index.html"
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"chat_enabled": chat_enabled},
    )


@app.get("/assistente", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not (settings.chat_enabled and settings.anthropic_api_key):
        return HTMLResponse("<h2>Assistente de IA desabilitado.</h2>", status_code=503)
    template = "chat_mobile.html" if _is_mobile(request) else "chat.html"
    return templates.TemplateResponse(request=request, name=template)


@app.get("/rdo", response_class=HTMLResponse)
async def rdo_page(request: Request):
    chat_enabled = settings.chat_enabled and bool(settings.anthropic_api_key)
    return templates.TemplateResponse(
        request=request, name="rdo.html", context={"chat_enabled": chat_enabled},
    )


@app.get("/progresso-civil", response_class=HTMLResponse)
async def progress_civil_page(request: Request):
    chat_enabled = settings.chat_enabled and bool(settings.anthropic_api_key)
    return templates.TemplateResponse(
        request=request, name="progress_civil.html", context={"chat_enabled": chat_enabled},
    )
