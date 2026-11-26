"""Ponte Inspector → ClickUp, com o ClickUp e o Claude dublados.

Cenário: Control Room de Lubango, space de laboratório "PEMx - RNA (Auto.)", inspeção de 20/11/2026
com o relato "Piso elevado 100% pronto".
"""
import base64
import json
from datetime import date

import pytest

from src.services import inspector_bridge as rules
from src.services.inspector_bridge_service import BridgeError, InspectorBridgeService
from src.services.schedule_fields import date_to_ms

LAB = "1400260000003694"
OTHER_SPACE = "901313804751"
STUDIO = "1400260000009472"


def _task(tid, name, parent=None, pct=0, status="planejando"):
    return {"id": tid, "name": name, "parent": parent, "status": {"status": status},
            "custom_fields": [{"id": "fp", "name": "% Concluído", "type": "manual_progress",
                               "value": {"current": str(pct)}}]}


TASKS = [
    _task("d1", "Civil Works"),
    _task("g1", "Floor", "d1"),
    _task("t1", "Raised technical floor installation", "g1", pct=40, status="fazendo"),
    _task("t2", "Skirting & finishing (after raised floor)", "g1"),
    _task("d2", "Acoustics"),
    _task("t3", "Acoustic panels installation", "d2", pct=60, status="fazendo"),
]


class FakeClickUp:
    def __init__(self, space=LAB):
        self.space = space
        self.calls = []

    async def get_folders(self, space_id):
        assert space_id == LAB
        return [{"id": "f1", "name": "LUBANGO", "lists": [{"id": STUDIO, "name": "STUDIO"}, {"id": "c1", "name": "CTP"}]},
                {"id": "f2", "name": "CAXITO - MABUBAS", "lists": []}]

    async def get_list(self, list_id):
        return {"id": list_id, "name": "STUDIO", "space": {"id": self.space},
                "statuses": [{"status": "planejando", "type": "open", "orderindex": 0},
                             {"status": "fazendo", "type": "custom", "orderindex": 1},
                             {"status": "complete", "type": "done", "orderindex": 2}]}

    async def get_tasks(self, list_id):
        return TASKS

    async def get_list_fields(self, list_id):
        return [{"id": "fp", "name": "% Concluído", "type": "manual_progress"},
                {"id": "fc", "name": "Data de Conclusão", "type": "date"}]

    async def create_comment(self, task_id, text, notify_all=True):
        self.calls.append(("comment", task_id, text))

    async def upload_attachment(self, task_id, filename, data, mime):
        self.calls.append(("attachment", task_id, filename))

    async def set_custom_field(self, task_id, field_id, value, value_options=None):
        self.calls.append(("field", task_id, field_id, value))

    async def set_task_status(self, task_id, status):
        self.calls.append(("status", task_id, status))


def _payload(**overrides):
    photo = base64.b64encode(b"jpeg-bytes").decode()
    data = {"key": "inspector-89-2026-11-20T06:35:00", "city": "LUBANGO",
            "room": "Control Room (Sala de Controle Técnico)", "recorded_at": "2026-11-20T06:33:53",
            "notes": "Piso elevado 100% pronto", "summary": "Piso elevado concluído.",
            "stages": [{"name": "Piso técnico", "status": "concluido", "percent": 100, "evidence": "placas assentes",
                        "source": "relato"}],
            "observations": ["FOTO ATUAL 1: piso elevado cinzento em toda a sala"],
            "photos": [{"filename": "cr_1.jpg", "mime": "image/jpeg", "data": photo, "comment": ""}],
            "inspector_url": "https://inspector.example/environments/2#historico"}
    data.update(overrides)
    return data


def _model(answer, seen=None):
    async def call(system, content, schema):
        if seen is not None:
            seen.update(system=system, content=content, schema=schema)
        return json.dumps(answer)
    return call


ANSWER = {"atualizacoes": [
    {"task_id": "t1", "evidencia": "Piso elevado assente em toda a sala", "fonte": "relato", "percentual": 100},
    {"task_id": "t3", "evidencia": "painéis não visíveis", "fonte": "foto", "percentual": 30},
], "observacao": ""}


# ─── regras puras ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("room,expected", [
    ("Control Room (Sala de Controle Técnico)", "STUDIO"),
    ("Announcer Room (Estúdio de Locução)", "STUDIO"),
    ("Technical Center (Centro Técnico)", "CTP"),
    ("Newsroom (Redação de Jornalismo)", "NEWSROOM"),
    ("Transmission Site (Centro de Transmissão)", "Site FM"),
    ("Sala qualquer", None),
])
def test_room_goes_to_its_list(room, expected):
    assert rules.room_list_name(room) == expected


def test_city_folder_matches_with_or_without_suffix():
    folders = [{"name": "LUBANGO"}, {"name": "CAXITO - MABUBAS"}, {"name": "UIGE - NEGAGE"}]
    assert rules.match_folder(folders, "Lubango")["name"] == "LUBANGO"
    assert rules.match_folder(folders, "CAXITO")["name"] == "CAXITO - MABUBAS"
    assert rules.match_folder(folders, "Huambo") is None


def test_candidates_are_leaves_with_their_path():
    candidates = {c.task_id: c for c in rules.leaf_candidates(TASKS)}
    assert set(candidates) == {"t1", "t2", "t3"}
    assert candidates["t1"].path == "Civil Works > Floor > Raised technical floor installation"
    assert candidates["t1"].percent == 40


def test_plan_never_lowers_and_rounds_to_five():
    candidates = rules.leaf_candidates(TASKS)
    raw = json.dumps({"atualizacoes": [
        {"task_id": "t1", "evidencia": "piso", "fonte": "foto", "percentual": 87},
        {"task_id": "t3", "evidencia": "painéis", "fonte": "foto", "percentual": 30},
        {"task_id": "zz", "evidencia": "x", "fonte": "foto", "percentual": 50}], "observacao": ""})
    plan = rules.plan_updates(raw, candidates)
    assert [(u.task_id, u.after) for u in plan.updates] == [("t1", 85)]
    assert any("não passa do atual 60%" in s for s in plan.skipped)
    assert any("desconhecida zz" in s for s in plan.skipped)


def test_schema_only_allows_tasks_of_the_list():
    schema = rules.response_schema(rules.leaf_candidates(TASKS))
    assert schema["properties"]["atualizacoes"]["items"]["properties"]["task_id"]["enum"] == ["t1", "t2", "t3"]


# ─── serviço ────────────────────────────────────────────────────────────────

async def test_updates_tasks_with_comment_photos_percent_and_completion_date():
    clickup, seen = FakeClickUp(), {}
    service = InspectorBridgeService(clickup, _model(ANSWER, seen), space_id=LAB, managed_lists=[])
    result = await service.process(_payload())

    assert [u["task_id"] for u in result["applied"]] == ["t1"]
    assert ("field", "t1", "fp", {"current": 100}) in clickup.calls
    assert ("field", "t1", "fc", date_to_ms(date(2026, 11, 20))) in clickup.calls   # dia da inspeção
    assert ("attachment", "t1", "cr_1.jpg") in clickup.calls
    assert ("status", "t1", "complete") in clickup.calls                             # lista sem o motor
    comment = next(c[2] for c in clickup.calls if c[0] == "comment")
    assert "40% → 100%" in comment and "segundo o relato" in comment and "Registo no Inspector" in comment
    assert not any(c[1] == "t3" for c in clickup.calls)                              # 30% < 60% atual
    # o modelo recebeu a foto e a lista de tarefas com o % atual
    assert seen["content"][1]["type"] == "image"
    assert "[t1] Civil Works > Floor > Raised technical floor installation — atual 40%" in seen["content"][-1]["text"]


async def test_on_a_schedule_list_the_engine_sets_the_status():
    clickup, notified = FakeClickUp(), []
    service = InspectorBridgeService(clickup, _model(ANSWER), space_id=LAB, managed_lists=[STUDIO],
                                     notify_list=notified.append)
    await service.process(_payload())
    assert not any(c[0] == "status" for c in clickup.calls)
    assert notified == [STUDIO]


async def test_refuses_a_list_outside_the_lab_space():
    clickup = FakeClickUp(space=OTHER_SPACE)
    service = InspectorBridgeService(clickup, _model(ANSWER), space_id=LAB, managed_lists=[])
    with pytest.raises(BridgeError, match="não pertence ao space de laboratório"):
        await service.process(_payload())
    assert clickup.calls == []


async def test_without_a_configured_space_nothing_is_written():
    clickup = FakeClickUp()
    with pytest.raises(BridgeError, match="não configurado"):
        await InspectorBridgeService(clickup, _model(ANSWER), space_id="", managed_lists=[]).process(_payload())
    assert clickup.calls == []


async def test_dry_run_only_proposes():
    clickup = FakeClickUp()
    result = await InspectorBridgeService(clickup, _model(ANSWER), space_id=LAB, managed_lists=[]).process(_payload(), dry_run=True)
    assert result["dry_run"] and [u["task_id"] for u in result["applied"]] == ["t1"]
    assert clickup.calls == []


async def test_unknown_room_or_city_is_reported():
    service = InspectorBridgeService(FakeClickUp(), _model(ANSWER), space_id=LAB, managed_lists=[])
    with pytest.raises(BridgeError, match="sem lista"):
        await service.process(_payload(room="Garagem"))
    with pytest.raises(BridgeError, match="sem pasta"):
        await service.process(_payload(city="HUILA"))


async def test_invalid_model_answer_is_an_error():
    async def broken(system, content, schema):
        return "não é json"
    with pytest.raises(BridgeError, match="inválida"):
        await InspectorBridgeService(FakeClickUp(), broken, space_id=LAB, managed_lists=[]).process(_payload())


# ─── rota ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def api(monkeypatch):
    import hashlib
    import hmac as hmac_mod
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.api import inspector_bridge as route
    from src.core.database import Base
    import src.models.inspector_bridge_models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(route, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(route.settings, "inspector_bridge_secret", "segredo")
    runs = []

    async def fake_run(key, payload, dry_run):
        runs.append((key, dry_run))
    monkeypatch.setattr(route, "_run", fake_run)

    app = FastAPI()
    app.include_router(route.router)
    sign = lambda body: hmac_mod.new(b"segredo", body, hashlib.sha256).hexdigest()  # noqa: E731
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, sign, runs
    await engine.dispose()


async def test_route_requires_the_signature(api):
    client, sign, runs = api
    body = json.dumps(_payload()).encode()
    assert (await client.post("/inspector/updates", content=body)).status_code == 401
    assert (await client.post("/inspector/updates", content=body, headers={"X-Inspector-Signature": "00"})).status_code == 401
    assert runs == []


async def test_route_accepts_once_per_key(api):
    client, sign, runs = api
    body = json.dumps(_payload()).encode()
    headers = {"X-Inspector-Signature": sign(body)}
    first = await client.post("/inspector/updates", content=body, headers=headers)
    second = await client.post("/inspector/updates", content=body, headers=headers)
    assert first.status_code == 202 and first.json()["status"] == "aceite"
    assert second.json()["status"] == "ja_recebido"
    assert runs == [("inspector-89-2026-11-20T06:35:00", False)]
    status = await client.get("/inspector/updates/inspector-89-2026-11-20T06:35:00",
                              headers={"X-Inspector-Signature": sign(b"inspector-89-2026-11-20T06:35:00")})
    assert status.json()["status"] == "recebido"


def test_the_model_is_told_which_rooms_share_the_list():
    text = rules.build_user_text(_payload(), rules.leaf_candidates(TASKS), 1, "STUDIO", rules.rooms_of_list("STUDIO"))
    assert "A lista STUDIO do ClickUp cobre estas salas: Announcer Room, Control Room" in text
    assert "Studio" not in rules.rooms_of_list("STUDIO")
    assert "vale para todas essas salas" in rules.SYSTEM_PROMPT


ANNOUNCER_STATE = {
    "room": "Announcer Room (Estúdio de Locução)", "last_record": "2026-11-26T14:24:38",
    "notes": "Porta, quadros, aquário e placa ON AIR concluídos",
    "stages": [{"name": "Tratamento acústico", "status": "concluido", "percent": 100,
                "evidence": "painéis e ripado instalados", "source": "ia"}],
}
NEWSROOM_STATE = {
    "room": "Newsroom (Redação de Jornalismo)", "last_record": "2026-11-25T10:00:00", "notes": "",
    "stages": [{"name": "Mobiliário", "status": "em_execucao", "percent": 30, "evidence": "mesas", "source": "ia"}],
}


def test_the_other_room_of_the_same_list_is_given_to_the_model():
    """STUDIO = locução + controle: a inspeção de uma sala chega com o estado atual da outra."""
    payload = _payload(other_rooms=[ANNOUNCER_STATE, NEWSROOM_STATE])
    text = rules.build_user_text(payload, rules.leaf_candidates(TASKS), 1, "STUDIO", rules.rooms_of_list("STUDIO"))
    assert "ESTADO ATUAL DAS OUTRAS SALAS DESTA LISTA" in text
    assert "Announcer Room (Estúdio de Locução)" in text
    assert "Tratamento acústico: concluido, 100%" in text
    assert "Porta, quadros, aquário e placa ON AIR concluídos" in text
    assert "Newsroom" not in text          # outra lista (NEWSROOM): não entra
    assert "combina esta inspeção com o estado das outras salas" in rules.SYSTEM_PROMPT


def test_without_the_other_room_the_model_is_told_it_was_not_seen():
    text = rules.build_user_text(_payload(), rules.leaf_candidates(TASKS), 1, "STUDIO", rules.rooms_of_list("STUDIO"))
    assert "Announcer Room: sem avaliação no Inspector" in text


def test_a_list_of_one_room_has_no_combination_section():
    payload = _payload(room="Newsroom (Redação de Jornalismo)", other_rooms=[ANNOUNCER_STATE])
    text = rules.build_user_text(payload, rules.leaf_candidates(TASKS), 1, "NEWSROOM", rules.rooms_of_list("NEWSROOM"))
    assert "OUTRAS SALAS" not in text and "Announcer" not in text
