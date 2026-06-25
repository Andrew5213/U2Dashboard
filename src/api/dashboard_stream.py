import asyncio
import json
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from src.core.config import settings
from src.core.logging import logger
from src.services.event_broadcaster import broadcaster

router = APIRouter(prefix="/dashboard", tags=["dashboard-stream"])


@router.get("/stream")
async def stream(request: Request):
    queue = await broadcaster.subscribe()
    logger.debug(f"SSE: novo cliente conectado (total={broadcaster.subscriber_count})")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=settings.sse_keepalive_seconds,
                    )
                    yield {"event": "update", "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(queue)
            logger.debug(f"SSE: cliente desconectado (total={broadcaster.subscriber_count})")

    return EventSourceResponse(event_generator())
