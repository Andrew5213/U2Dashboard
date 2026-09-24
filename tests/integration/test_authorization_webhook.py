"""Assinatura do webhook do módulo de Autorização de Serviço (POST /webhooks/autorizacoes)."""
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import authorizations

SECRET = "auth_secret"


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(authorizations.webhook_router)
    return app


def _signed_body(secret: str = SECRET) -> tuple[bytes, str]:
    """Corpo cru + assinatura como o ClickUp envia (hex puro do HMAC-SHA256)."""
    body = json.dumps({"event": "taskCreated", "task_id": "t1"}).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _post(app: FastAPI, body: bytes, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/webhooks/autorizacoes", content=body, headers=headers)


@pytest.mark.asyncio
async def test_valid_signature_notifies_approver(app):
    body, signature = _signed_body()

    with patch("src.api.authorizations.settings") as mock_settings, \
         patch("src.api.authorizations._notify_approver") as notify, \
         patch("src.api.authorizations.asyncio.create_task") as create_task:
        mock_settings.authorization_webhook_secret = SECRET
        resp = await _post(app, body, signature)

    assert resp.json() == {"status": "ok"}
    notify.assert_called_once_with("t1")
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_missing_signature_is_rejected_when_secret_is_set(app):
    body, _ = _signed_body()

    with patch("src.api.authorizations.settings") as mock_settings, \
         patch("src.api.authorizations.asyncio.create_task") as create_task:
        mock_settings.authorization_webhook_secret = SECRET
        resp = await _post(app, body, None)

    assert resp.json() == {"status": "invalid_signature"}
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_signature_is_rejected_when_secret_is_set(app):
    body, _ = _signed_body()

    with patch("src.api.authorizations.settings") as mock_settings, \
         patch("src.api.authorizations.asyncio.create_task") as create_task:
        mock_settings.authorization_webhook_secret = SECRET
        resp = await _post(app, body, "0" * 64)

    assert resp.json() == {"status": "invalid_signature"}
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_unsigned_request_is_accepted_when_no_secret_is_configured(app):
    body, _ = _signed_body()

    with patch("src.api.authorizations.settings") as mock_settings, \
         patch("src.api.authorizations._notify_approver"), \
         patch("src.api.authorizations.asyncio.create_task") as create_task:
        mock_settings.authorization_webhook_secret = ""
        resp = await _post(app, body, None)

    assert resp.json() == {"status": "ok"}
    create_task.assert_called_once()
