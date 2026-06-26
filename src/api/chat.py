from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import get_db
from src.models.chat_schemas import ChatRequest, ChatResponse
from src.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _check_enabled() -> None:
    if not settings.chat_enabled:
        raise HTTPException(status_code=503, detail="Assistente de IA desabilitado (CHAT_ENABLED=false).")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Assistente de IA não configurado (ANTHROPIC_API_KEY ausente).")


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    _check_enabled()
    svc = ChatService(db)
    return await svc.ask(request.message)


@router.get("/status")
async def chat_status() -> dict:
    enabled = settings.chat_enabled and bool(settings.anthropic_api_key)
    return {"enabled": enabled, "model": settings.chat_model if enabled else None}
