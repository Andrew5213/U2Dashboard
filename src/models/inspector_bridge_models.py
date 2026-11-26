from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class InspectorBridgeRun(Base):
    """Um registo do Broadcast Inspector recebido pela ponte (uma linha por chave).

    A chave vem do Inspector (registo + data da análise): reenvios da mesma análise não regravam
    nada; uma reanálise gera chave nova.
    """
    __tablename__ = "inspector_bridge_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    city: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    room: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    list_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # recebido | concluido | erro | ensaio
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="recebido")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
