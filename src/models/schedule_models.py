from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, String, func
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


class ScheduleBaseline(Base):
    """Linha de base do cronograma: início e término planeados de cada tarefa no
    momento em que o plano foi fixado.

    O motor reprograma as datas no ClickUp conforme o andamento real, então uma
    tarefa nunca fica "em atraso" por lá — o atraso só aparece comparando o término
    de hoje com o que está guardado aqui. É gravada sozinha no primeiro cálculo de
    uma lista e só muda quando alguém a redefine (`POST /schedule/{id}/baseline`)."""
    __tablename__ = "schedule_baseline"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    list_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    start: Mapped[date] = mapped_column(Date, nullable=False)
    finish: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
