"""Endpoints do módulo de Autorização de Serviço.

Dois routers distintos:
  * `webhook_router` — recebe o taskCreated do Space de autorizações. Endpoint
    separado de /webhooks/clickup de propósito: aquele empurra tudo para o
    SyncService (Airbox) e para o cache do dashboard, o que não faz sentido aqui.
  * `router` — a página de confirmação que o gestor abre a partir do e-mail.
"""
import asyncio

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal, get_db
from src.core.logging import logger
from src.core.webhook_security import verify_clickup_signature
from src.services.authorization_service import AuthorizationError, AuthorizationService

webhook_router = APIRouter(prefix="/webhooks", tags=["autorizações"])
router = APIRouter(prefix="/autorizacoes", tags=["autorizações"])

templates = Jinja2Templates(directory="src/templates")

_TEMPLATE = "authorization_decision.html"


async def _notify_approver(task_id: str) -> None:
    """Roda fora do ciclo do webhook: o ClickUp não pode esperar o SMTP."""
    try:
        async with AsyncSessionLocal() as db:
            await AuthorizationService(db).handle_task_created(task_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Autorização: falha ao notificar gestor sobre {task_id}: {exc}")


@webhook_router.post("/autorizacoes", summary="Webhook do Space de autorizações")
async def receive_authorization_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
):
    body = await request.body()
    if not verify_clickup_signature(settings.authorization_webhook_secret, body, x_signature):
        logger.warning("Webhook de autorizações: assinatura inválida")
        return {"status": "invalid_signature"}

    payload = await request.json()
    event = payload.get("event", "")
    task_id = payload.get("task_id")

    if event != "taskCreated" or not task_id:
        return {"status": "ignored", "event": event}

    asyncio.create_task(_notify_approver(task_id))
    return {"status": "ok"}


@router.get("/decidir/{token}", response_class=HTMLResponse, summary="Página de confirmação")
async def decision_page(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """Somente leitura. O prefetch de link feito por clientes de e-mail e
    antivírus cai aqui e não decide nada."""
    try:
        context = await AuthorizationService(db).get_decision_context(token)
    except AuthorizationError as exc:
        return _render(request, {"error": str(exc)}, status_code=410)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Autorização: erro ao abrir token: {exc}")
        return _render(request, {"error": "Não foi possível carregar a requisição."}, 502)
    return _render(request, context)


@router.post("/decidir/{token}", response_class=HTMLResponse, summary="Confirmar decisão")
async def submit_decision(
    request: Request,
    token: str,
    note: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    service = AuthorizationService(db)
    try:
        result = await service.apply_decision(token, note)
        await db.commit()
    except AuthorizationError as exc:
        await db.rollback()
        try:
            context = await service.get_decision_context(token)
        except AuthorizationError:
            return _render(request, {"error": str(exc)}, status_code=410)
        return _render(request, {**context, "form_error": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error(f"Autorização: erro ao aplicar decisão: {exc}")
        return _render(
            request,
            {"error": "Falha ao registrar a decisão no ClickUp. Tente novamente."},
            502,
        )
    return _render(request, {"result": result})


def _render(request: Request, context: dict, status_code: int = 200) -> HTMLResponse:
    """`no-store` é obrigatório aqui: a página carrega dados do pedido e o 410 de
    token inválido é cacheável por padrão — sem isso o navegador guarda o erro e
    continua mostrando "link inválido" mesmo depois de o link passar a valer."""
    response = templates.TemplateResponse(
        request=request, name=_TEMPLATE, context=context, status_code=status_code
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response
