from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ScheduleTaskState(Base):
    """Último (%, concluída?) que o motor do cronograma viu em cada tarefa.

    Serve para saber o que o utilizador acabou de mexer quando % e status
    discordam: baixar o % de uma tarefa concluída reabre a tarefa, enquanto
    marcar "complete" numa tarefa a 40% leva o % a 100."""
    __tablename__ = "schedule_task_state"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    list_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
