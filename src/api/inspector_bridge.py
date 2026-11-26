"""POST /inspector/updates — o Broadcast Inspector envia aqui cada análise de fotos de uma sala.

Corpo JSON (assinado com HMAC-SHA256 do corpo cru, hex, cabeçalho X-Inspector-Signature):
  key, city, room, recorded_at, notes, summary, stages[], observations[], photos[{filename, mime, data(b64), comment}],
  inspector_url, dry_run (opcional)
A resposta é imediata (202); o trabalho (Claude + gravações no ClickUp) corre em segundo plano e o resultado
fica em GET /inspector/updates/{key}.
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import select

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import logger
from src.models.inspector_bridge_models import InspectorBridgeRun
from src.services.clickup_client import ClickUpClient
from src.services.inspector_bridge_service import BridgeError, InspectorBridgeService
from src.workers.schedule_worker import notify_list_changed

router = APIRouter(prefix="/inspector", tags=["inspector"])

# Uma execução de cada vez: duas leituras da mesma lista em paralelo partiriam do mesmo % e uma
# gravação apagaria a outra.
_lock = asyncio.Lock()


def _signature_ok(body: bytes, signature: str | None) -> bool:
    if not settings.inspector_bridge_secret or not signature:
        return False
    expected = hmac.new(settings.inspector_bridge_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.strip().lower().encode())


async def _run(key: str, payload: dict, dry_run: bool) -> None:
    status, result, error, list_id = "erro", {}, "", None
    async with _lock:
        try:
            async with ClickUpClient() as clickup:
                result = await InspectorBridgeService(clickup, notify_list=notify_list_changed).process(payload, dry_run)
            list_id = result.get("list_id")
            status = "ensaio" if dry_run else "concluido"
            logger.info(f"Ponte Inspector {key}: {len(result['applied'])} tarefa(s) "
                        f"{'propostas' if dry_run else 'atualizadas'} na lista {list_id}")
        except BridgeError as exc:
            error = str(exc)
            logger.warning(f"Ponte Inspector {key}: {error}")
        except Exception as exc:  # noqa: BLE001
            error = f"erro inesperado: {exc}"
            logger.exception(f"Ponte Inspector {key}: falha")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(InspectorBridgeRun).where(InspectorBridgeRun.key == key))).scalar_one()
        row.status, row.error, row.list_id = status, error[:2000], list_id
        row.result_json = json.dumps(result, ensure_ascii=False, default=str)
        row.finished_at = datetime.utcnow()
        await db.commit()


@router.post("/updates", status_code=202)
async def receive_update(request: Request, background: BackgroundTasks):
    if not settings.inspector_bridge_secret:
        raise HTTPException(503, "INSPECTOR_BRIDGE_SECRET não configurado")
    body = await request.body()
    if not _signature_ok(body, request.headers.get("X-Inspector-Signature")):
        raise HTTPException(401, "assinatura inválida")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, "JSON inválido")
    key = str(payload.get("key") or "").strip()[:200]
    if not key or not payload.get("city") or not payload.get("room"):
        raise HTTPException(422, "key, city e room são obrigatórios")
    dry_run = bool(payload.get("dry_run"))

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(InspectorBridgeRun).where(InspectorBridgeRun.key == key))).scalar_one_or_none()
        if row and row.status in ("recebido", "concluido"):
            return {"status": "ja_recebido", "key": key, "estado": row.status}
        if row:  # erro ou ensaio anterior: tenta de novo
            row.status, row.error, row.result_json, row.finished_at = "recebido", "", "{}", None
        else:
            db.add(InspectorBridgeRun(key=key, city=str(payload["city"])[:200], room=str(payload["room"])[:200]))
        await db.commit()
    background.add_task(_run, key, payload, dry_run)
    return {"status": "aceite", "key": key, "dry_run": dry_run}


@router.get("/updates/{key}")
async def update_status(key: str, request: Request):
    # A consulta assina a própria chave, para não expor o resultado a quem não tem o segredo.
    if not _signature_ok(key.encode(), request.headers.get("X-Inspector-Signature")):
        raise HTTPException(401, "assinatura inválida")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(InspectorBridgeRun).where(InspectorBridgeRun.key == key))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "chave desconhecida")
    return {"key": key, "status": row.status, "error": row.error, "list_id": row.list_id,
            "result": json.loads(row.result_json or "{}"), "received_at": row.received_at, "finished_at": row.finished_at}
