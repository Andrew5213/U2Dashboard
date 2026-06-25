from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


class TaskSyncMap(Base):
    """Maps Airbox task IDs to ClickUp task IDs."""

    __tablename__ = "task_sync_map"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    airbox_task_id: Mapped[int] = mapped_column(unique=True, index=True)
    clickup_task_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    airbox_agreement_id: Mapped[int] = mapped_column(index=True)
    clickup_list_id: Mapped[str] = mapped_column(String(100))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgreementSyncMap(Base):
    """Maps Airbox agreement IDs to ClickUp list IDs."""

    __tablename__ = "agreement_sync_map"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    airbox_agreement_id: Mapped[int] = mapped_column(index=True)
    airbox_agreement_name: Mapped[str] = mapped_column(String(255))
    airbox_agreement_type: Mapped[str] = mapped_column(String(50))  # project | procedure | service
    clickup_list_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    clickup_space_id: Mapped[str] = mapped_column(String(100))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncLog(Base):
    """Audit log for all sync operations."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    direction: Mapped[str] = mapped_column(String(20))        # "to_clickup" | "to_airbox"
    entity_type: Mapped[str] = mapped_column(String(50))      # "task" | "agreement"
    entity_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))           # "created" | "updated"
    status: Mapped[str] = mapped_column(String(20))           # "success" | "error"
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
