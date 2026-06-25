from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any


# ─── Airbox Schemas ───────────────────────────────────────────────────────────

class AirboxTask(BaseModel):
    id: int | None = None
    name: str | None = None
    company_id: int | None = None
    entity_type: str | None = None   # "Agreement" na API real
    entity_id: int | None = None
    task_stage_id: int | None = None
    position: int | None = None
    customer_id: int | None = None
    responsible_id: int | None = None
    information: str | None = None
    started: str | None = None          # ISO 8601
    start_prediction: str | None = None # ISO 8601
    finish_prediction: str | None = None# ISO 8601
    finished: str | None = None         # ISO 8601
    due_date: str | None = None         # ISO 8601
    estimated_hours: float = 0
    code: str | None = None             # código auto-gerado (ex: "RNACU001-1")
    is_archived: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class AirboxAgreement(BaseModel):
    id: int
    name: str | None = None
    additional_info: str | None = None
    type: str | None = None          # "project" | "procedure" | "service"
    contract_id: int | None = None
    state: int | None = None         # 0=active, 1=suspended, 2=closed, 3=canceled
    default_responsible_id: int | None = None
    starting: int | None = None      # unix timestamp ms
    revenue_value: float | None = None


class AirboxUser(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    avatar: str | None = None


# ─── ClickUp Schemas ──────────────────────────────────────────────────────────

class ClickUpTask(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    status: str | None = None
    assignees: list[dict[str, Any]] = Field(default_factory=list)
    due_date: int | None = None      # unix timestamp ms
    start_date: int | None = None    # unix timestamp ms
    time_estimate: int | None = None # milliseconds
    tags: list[str] = Field(default_factory=list)
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    list_id: str | None = None


class ClickUpWebhookEvent(BaseModel):
    event: str
    task_id: str | None = None
    history_items: list[dict[str, Any]] = Field(default_factory=list)
    webhook_id: str | None = None


# ─── Sync Schemas ─────────────────────────────────────────────────────────────

class SyncResult(BaseModel):
    success: bool
    entity_type: str
    entity_id: str
    action: str
    message: str
    error: str | None = None


class SyncStatus(BaseModel):
    total_agreements: int
    total_tasks: int
    last_sync: datetime | None
    errors: int
