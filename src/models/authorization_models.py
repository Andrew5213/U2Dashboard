from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base

ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"


class AuthorizationToken(Base):
    """Token de uso único que permite ao gestor decidir uma autorização de serviço
    direto do e-mail, sem abrir o ClickUp.

    Cada requisição gera um par de tokens (aprovar / recusar). Usar um deles
    invalida o irmão — a decisão é definitiva e não pode ser reexecutada.
    """
    __tablename__ = "authorization_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # approve | reject
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_note: Mapped[str | None] = mapped_column(Text, nullable=True)
