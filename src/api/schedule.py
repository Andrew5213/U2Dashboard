import dataclasses
import secrets

from fastapi import APIRouter, Header, HTTPException

from src.core.config import settings
from src.workers.schedule_worker import is_schedule_list, run_recalculation

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/lists")
async def schedule_lists():
    return {"enabled": settings.schedule_enabled, "list_ids": settings.schedule_lists}


@router.post("/{list_id}/recalculate")
async def recalculate(
    list_id: str,
    dry_run: bool = False,
    x_delete_password: str | None = Header(None, alias="X-Delete-Password"),
):
    """Recalcula o cronograma da lista. `dry_run=true` só mostra o que mudaria;
    gravar exige a senha partilhada das demais escritas da app."""
    if not is_schedule_list(list_id):
        raise HTTPException(status_code=404, detail="Lista não configurada como cronograma (SCHEDULE_LIST_IDS)")
    if not dry_run and not secrets.compare_digest(
        (x_delete_password or "").encode(), settings.documents_delete_password.encode()
    ):
        raise HTTPException(status_code=403, detail="Senha incorreta")
    return dataclasses.asdict(await run_recalculation(list_id, dry_run=dry_run))


@router.post("/{list_id}/baseline")
async def rebaseline(
    list_id: str,
    x_delete_password: str | None = Header(None, alias="X-Delete-Password"),
):
    """Adota o cronograma atual como a nova linha de base da lista: o atraso volta a
    zero e passa a ser medido a partir daqui. Não grava nada no ClickUp."""
    if not is_schedule_list(list_id):
        raise HTTPException(status_code=404, detail="Lista não configurada como cronograma (SCHEDULE_LIST_IDS)")
    if not secrets.compare_digest(
        (x_delete_password or "").encode(), settings.documents_delete_password.encode()
    ):
        raise HTTPException(status_code=403, detail="Senha incorreta")
    summary = await run_recalculation(list_id, dry_run=True, rebaseline=True)
    if summary.errors:
        raise HTTPException(status_code=409, detail="; ".join(summary.errors))
    return {
        "list_id": list_id,
        "tasks": summary.tasks,
        "baseline_finish": summary.baseline_finish,
        "project_finish": summary.project_finish,
        "delay_days": summary.delay_days,
    }
