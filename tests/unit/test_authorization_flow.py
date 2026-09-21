"""Ciclo de vida dos tokens e do fluxo de decisão, contra SQLite em memória.

O ClickUp e o SMTP são substituídos por dublês — o que importa aqui é a máquina
de estados: token de uso único, irmão invalidado, expiração e obrigatoriedade do
motivo na recusa.
"""
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base
from src.models.authorization_models import ACTION_APPROVE, ACTION_REJECT
from src.repositories.authorization_repository import AuthorizationRepository, utcnow
from src.services import authorization_service as svc_module
from src.services.authorization_service import AuthorizationError, AuthorizationService

TEST_DB = "sqlite+aiosqlite:///:memory:"

TASK = {
    "id": "abc123",
    "name": "Autorização — Transmissor — FM Namibe",
    "url": "https://app.clickup.com/t/abc123",
    "list": {"id": "999"},
    "status": {"status": "Solicitado"},
    "custom_fields": [
        {"id": "f1", "name": "Motivo", "type": "text", "value": "Trocar módulo de PA"},
        {"id": "f2", "name": "Solicitante", "type": "users",
         "value": [{"username": "Eduardo", "email": "eduardo@u2.ao"}]},
        {"id": "f3", "name": "Decidido Por", "type": "short_text"},
        {"id": "f4", "name": "Data da Decisão", "type": "date"},
        {"id": "f5", "name": "Observações da Decisão", "type": "text"},
    ],
}


class FakeClickUpClient:
    """Registra as chamadas em vez de bater na API."""
    calls: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get_task(self, task_id: str) -> dict:
        return TASK

    async def get_list_fields(self, list_id: str) -> list[dict]:
        return [{"id": f["id"], "name": f["name"]} for f in TASK["custom_fields"]]

    async def set_task_name(self, task_id: str, name: str) -> dict:
        FakeClickUpClient.calls["name"] = name
        TASK["name"] = name
        return {}

    async def set_task_status(self, task_id: str, status: str) -> dict:
        FakeClickUpClient.calls["status"] = status
        return {}

    async def set_custom_field(
        self, task_id: str, field_id: str, value: object, value_options: dict | None = None
    ) -> dict:
        FakeClickUpClient.calls.setdefault("fields", {})[field_id] = value
        FakeClickUpClient.calls.setdefault("field_options", {})[field_id] = value_options
        return {}

    async def create_comment(self, task_id: str, comment_text: str, notify_all: bool = True) -> dict:
        FakeClickUpClient.calls["comment"] = comment_text
        return {}


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def fake_clickup_and_smtp(monkeypatch):
    FakeClickUpClient.calls = {}
    sent: list[dict] = []

    monkeypatch.setattr(svc_module, "ClickUpClient", FakeClickUpClient)
    svc_module._FIELD_ID_CACHE.clear()

    async def _fake_send(self, subject, html, recipients):
        sent.append({"subject": subject, "html": html, "recipients": recipients})
        return True

    monkeypatch.setattr(AuthorizationService, "_send", _fake_send)
    return sent


# ─── Tokens ──────────────────────────────────────────────────────────────────

class TestTokenPair:
    async def test_pair_has_two_distinct_tokens(self, db):
        pair = await AuthorizationRepository(db).create_pair("t1", "Pedido", 7)
        assert set(pair) == {ACTION_APPROVE, ACTION_REJECT}
        assert pair[ACTION_APPROVE].token != pair[ACTION_REJECT].token

    async def test_consuming_one_invalidates_the_sibling(self, db):
        repo = AuthorizationRepository(db)
        pair = await repo.create_pair("t1", "Pedido", 7)
        await repo.consume(pair[ACTION_APPROVE].token, "ok")

        sibling = await repo.get_by_token(pair[ACTION_REJECT].token)
        assert sibling.used_at is not None

    async def test_has_tokens_for_task(self, db):
        repo = AuthorizationRepository(db)
        assert await repo.has_tokens_for_task("t1") is False
        await repo.create_pair("t1", "Pedido", 7)
        assert await repo.has_tokens_for_task("t1") is True


# ─── Decisão ─────────────────────────────────────────────────────────────────

class TestApplyDecision:
    async def _pair(self, db):
        return await AuthorizationRepository(db).create_pair(
            TASK["id"], TASK["name"], 7
        )

    async def test_approve_sets_status_and_writes_fields(self, db, monkeypatch):
        monkeypatch.setattr(svc_module.settings, "authorization_status_approved", "Autorizado")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_name", "Chefe")
        pair = await self._pair(db)

        result = await AuthorizationService(db).apply_decision(
            pair[ACTION_APPROVE].token, "pode ir amanhã"
        )

        assert result["approved"] is True
        assert FakeClickUpClient.calls["status"] == "Autorizado"
        assert FakeClickUpClient.calls["fields"]["f3"] == "Chefe"       # Decidido Por
        assert isinstance(FakeClickUpClient.calls["fields"]["f4"], int)  # Data da Decisão (epoch ms)
        # sem value_options o ClickUp trunca a data para meia-noite do fuso do workspace
        assert FakeClickUpClient.calls["field_options"]["f4"] == {"time": True}
        assert FakeClickUpClient.calls["fields"]["f5"] == "pode ir amanhã"
        assert "AUTORIZADO" in FakeClickUpClient.calls["comment"]

    async def test_reject_requires_reason(self, db):
        pair = await self._pair(db)
        with pytest.raises(AuthorizationError):
            await AuthorizationService(db).apply_decision(pair[ACTION_REJECT].token, "")
        assert "status" not in FakeClickUpClient.calls

    async def test_reject_with_reason_sets_status(self, db, monkeypatch):
        monkeypatch.setattr(svc_module.settings, "authorization_status_rejected", "Recusado")
        pair = await self._pair(db)

        result = await AuthorizationService(db).apply_decision(
            pair[ACTION_REJECT].token, "site sem energia"
        )

        assert result["approved"] is False
        assert FakeClickUpClient.calls["status"] == "Recusado"

    async def test_token_cannot_be_reused(self, db):
        pair = await self._pair(db)
        service = AuthorizationService(db)
        await service.apply_decision(pair[ACTION_APPROVE].token, "")

        with pytest.raises(AuthorizationError):
            await service.apply_decision(pair[ACTION_APPROVE].token, "")

    async def test_sibling_token_is_dead_after_decision(self, db):
        pair = await self._pair(db)
        service = AuthorizationService(db)
        await service.apply_decision(pair[ACTION_APPROVE].token, "")

        with pytest.raises(AuthorizationError):
            await service.apply_decision(pair[ACTION_REJECT].token, "mudei de ideia")

    async def test_expired_token_is_refused(self, db):
        repo = AuthorizationRepository(db)
        pair = await repo.create_pair(TASK["id"], TASK["name"], 7)
        row = await repo.get_by_token(pair[ACTION_APPROVE].token)
        row.expires_at = utcnow() - timedelta(seconds=1)
        await db.flush()

        with pytest.raises(AuthorizationError):
            await AuthorizationService(db).apply_decision(row.token, "")

    async def test_unknown_token_is_refused(self, db):
        with pytest.raises(AuthorizationError):
            await AuthorizationService(db).apply_decision("nao-existe", "")

    async def test_requester_is_notified(self, db, fake_clickup_and_smtp):
        pair = await self._pair(db)
        await AuthorizationService(db).apply_decision(pair[ACTION_APPROVE].token, "")

        assert any("eduardo@u2.ao" in mail["recipients"] for mail in fake_clickup_and_smtp)

    async def test_requester_notified_flag_reflects_actual_send(self, db, monkeypatch):
        async def _fail_send(self, subject, html, recipients):
            return False

        monkeypatch.setattr(AuthorizationService, "_send", _fail_send)
        pair = await self._pair(db)
        result = await AuthorizationService(db).apply_decision(pair[ACTION_APPROVE].token, "")
        assert result["requester_notified"] is False


# ─── Entrada pelo webhook ────────────────────────────────────────────────────

class TestHandleTaskCreated:
    async def test_sends_email_to_approver(self, db, monkeypatch, fake_clickup_and_smtp):
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "999")
        monkeypatch.setattr(svc_module.settings, "authorization_status_pending", "Solicitado")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        assert await AuthorizationService(db).handle_task_created(TASK["id"]) is True
        assert fake_clickup_and_smtp[0]["recipients"] == ["chefe@u2.ao"]

    async def test_is_idempotent(self, db, monkeypatch, fake_clickup_and_smtp):
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "999")
        monkeypatch.setattr(svc_module.settings, "authorization_status_pending", "Solicitado")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        service = AuthorizationService(db)
        assert await service.handle_task_created(TASK["id"]) is True
        assert await service.handle_task_created(TASK["id"]) is False
        assert len(fake_clickup_and_smtp) == 1

    async def test_ignores_task_from_another_list(self, db, monkeypatch, fake_clickup_and_smtp):
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "outra")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        assert await AuthorizationService(db).handle_task_created(TASK["id"]) is False
        assert fake_clickup_and_smtp == []

    async def test_renames_task_to_the_standard_pattern(self, db, monkeypatch, fake_clickup_and_smtp):
        """O ClickUp não nomeia submissões de Form com os valores dos campos —
        quem padroniza o título (e o assunto do e-mail) é o backend."""
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "999")
        monkeypatch.setattr(svc_module.settings, "authorization_status_pending", "Solicitado")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        original = TASK["name"]
        TASK["custom_fields"] = TASK["custom_fields"] + [
            {"id": "f6", "name": "Equipamento", "type": "short_text", "value": "Gerador"},
            {"id": "f7", "name": "Site / Estúdio", "type": "short_text", "value": "FM Namibe"},
        ]
        try:
            await AuthorizationService(db).handle_task_created(TASK["id"])
            assert FakeClickUpClient.calls["name"] == "Gerador — FM Namibe"
            assert "Gerador — FM Namibe" in fake_clickup_and_smtp[0]["subject"]
        finally:
            TASK["name"] = original
            TASK["custom_fields"] = TASK["custom_fields"][:-2]

    async def test_does_not_rename_when_fields_are_empty(self, db, monkeypatch, fake_clickup_and_smtp):
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "999")
        monkeypatch.setattr(svc_module.settings, "authorization_status_pending", "Solicitado")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        await AuthorizationService(db).handle_task_created(TASK["id"])
        assert "name" not in FakeClickUpClient.calls

    async def test_ignores_task_not_in_initial_status(self, db, monkeypatch, fake_clickup_and_smtp):
        monkeypatch.setattr(svc_module.settings, "authorization_list_id", "999")
        monkeypatch.setattr(svc_module.settings, "authorization_status_pending", "Aguardando")
        monkeypatch.setattr(svc_module.settings, "authorization_approver_email", "chefe@u2.ao")

        assert await AuthorizationService(db).handle_task_created(TASK["id"]) is False
        assert fake_clickup_and_smtp == []
