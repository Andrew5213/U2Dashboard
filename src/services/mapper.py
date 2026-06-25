from datetime import datetime, timezone
from src.models.schemas import AirboxTask, ClickUpTask


def _iso_to_unix_ms(iso: str | None) -> int | None:
    """Converte data ISO 8601 (Airbox) para unix timestamp em milissegundos (ClickUp)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def _unix_ms_to_iso(ms_str: str | int | None) -> str | None:
    """Converte unix timestamp em ms (ClickUp) para ISO 8601 (Airbox)."""
    if not ms_str:
        return None
    try:
        dt = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (ValueError, OverflowError, OSError):
        return None

# ─── ClickUp → Airbox ────────────────────────────────────────────────────────

# Mapeamento de status name do ClickUp → task_stage_id do Airbox.
# Preencha após descobrir os IDs reais dos stages no Airbox.
# Exemplo: CLICKUP_STATUS_TO_AIRBOX_STAGE = {"to do": 1, "in progress": 2, "complete": 3}
CLICKUP_STATUS_TO_AIRBOX_STAGE: dict[str, int] = {}


def clickup_task_to_airbox(
    cu_task: dict,
    agreement_id: int,
    entity_type: str = "Agreement",
    airbox_responsible_id: int | None = None,
) -> dict:
    """Converte uma task lida da API do ClickUp para o payload de criação no Airbox.

    entity_type deve ser "Agreement" (valor real esperado pela API do AltoQI Visus Workflow).
    """
    status_name = ""
    if isinstance(cu_task.get("status"), dict):
        status_name = cu_task["status"].get("status", "").lower()

    stage_id = CLICKUP_STATUS_TO_AIRBOX_STAGE.get(status_name)

    description = cu_task.get("description") or cu_task.get("markdown_description") or ""

    payload: dict = {
        "entity_type": entity_type,
        "entity_id": agreement_id,
        "name": cu_task.get("name", ""),
    }

    if description:
        payload["information"] = description
    if stage_id is not None:
        payload["task_stage_id"] = stage_id
    if cu_task.get("due_date"):
        iso = _unix_ms_to_iso(cu_task["due_date"])
        if iso:
            payload["due_date"] = iso
    if cu_task.get("start_date"):
        iso = _unix_ms_to_iso(cu_task["start_date"])
        if iso:
            payload["started"] = iso
    if airbox_responsible_id is not None:
        payload["responsible_id"] = airbox_responsible_id

    return payload


# ─── Airbox → ClickUp ────────────────────────────────────────────────────────

# IDs dos custom fields no ClickUp (configure após criar os campos na workspace).
CLICKUP_FIELD_AIRBOX_TASK_ID: str | None = None
CLICKUP_FIELD_AIRBOX_STAGE_ID: str | None = None

# Mapeamento inverso: task_stage_id (Airbox) → status name (ClickUp).
AIRBOX_STAGE_TO_CLICKUP_STATUS: dict[int, str] = {}


def airbox_task_to_clickup(task: AirboxTask) -> ClickUpTask:
    """Converte uma task do Airbox para o formato de escrita no ClickUp."""
    status = None
    if task.task_stage_id is not None:
        status = AIRBOX_STAGE_TO_CLICKUP_STATUS.get(task.task_stage_id)

    custom_fields: list[dict] = []
    if task.id is not None and CLICKUP_FIELD_AIRBOX_TASK_ID:
        custom_fields.append({"id": CLICKUP_FIELD_AIRBOX_TASK_ID, "value": str(task.id)})
    if task.task_stage_id is not None and CLICKUP_FIELD_AIRBOX_STAGE_ID:
        custom_fields.append({"id": CLICKUP_FIELD_AIRBOX_STAGE_ID, "value": str(task.task_stage_id)})

    description_parts = []
    if task.information:
        description_parts.append(task.information)

    return ClickUpTask(
        name=task.name or f"Tarefa #{task.id}",
        description="\n\n".join(description_parts) or None,
        status=status,
        start_date=_iso_to_unix_ms(task.started),
        due_date=_iso_to_unix_ms(task.due_date),
        custom_fields=custom_fields,
    )


def clickup_to_airbox_fields(history_items: list[dict]) -> dict:
    """Extrai campos para atualização no Airbox a partir de um webhook do ClickUp.

    Nota: a API pública do Airbox não expõe PATCH /tasks.
    Este mapeamento existe para uso futuro quando a API for ampliada.
    """
    fields: dict = {}
    for item in history_items:
        field = item.get("field")
        new_value = item.get("after")

        if field == "name":
            fields["name"] = new_value
        elif field == "due_date" and new_value:
            iso = _unix_ms_to_iso(new_value)
            if iso:
                fields["due_date"] = iso
        elif field == "status":
            status_name = new_value.get("status", "").lower() if isinstance(new_value, dict) else str(new_value).lower()
            stage_id = CLICKUP_STATUS_TO_AIRBOX_STAGE.get(status_name)
            if stage_id is not None:
                fields["task_stage_id"] = stage_id

    return fields
