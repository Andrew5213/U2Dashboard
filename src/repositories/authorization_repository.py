import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.authorization_models import ACTION_APPROVE, ACTION_REJECT, AuthorizationToken

_TOKEN_BYTES = 32


def utcnow() -> datetime:
    """UTC naive — coerente com as colunas DateTime do SQLite usadas no projeto."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthorizationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_pair(
        self, task_id: str, task_name: str, ttl_days: int
    ) -> dict[str, AuthorizationToken]:
        """Cria o par de tokens (approve/reject) de uma requisição."""
        expires_at = utcnow() + timedelta(days=ttl_days)
        pair: dict[str, AuthorizationToken] = {}
        for action in (ACTION_APPROVE, ACTION_REJECT):
            row = AuthorizationToken(
                task_id=task_id,
                task_name=task_name[:500],
                action=action,
                token=secrets.token_urlsafe(_TOKEN_BYTES),
                expires_at=expires_at,
            )
            self._db.add(row)
            pair[action] = row
        await self._db.flush()
        return pair

    async def get_by_token(self, token: str) -> AuthorizationToken | None:
        result = await self._db.execute(
            select(AuthorizationToken).where(AuthorizationToken.token == token)
        )
        return result.scalar_one_or_none()

    async def list_by_task(self, task_id: str) -> list[AuthorizationToken]:
        result = await self._db.execute(
            select(AuthorizationToken).where(AuthorizationToken.task_id == task_id)
        )
        return list(result.scalars().all())

    async def has_tokens_for_task(self, task_id: str) -> bool:
        return bool(await self.list_by_task(task_id))

    async def consume(self, token: str, note: str | None) -> None:
        """Marca o token como usado e invalida todos os irmãos da mesma tarefa."""
        row = await self.get_by_token(token)
        if row is None:
            return
        now = utcnow()
        await self._db.execute(
            update(AuthorizationToken)
            .where(
                AuthorizationToken.task_id == row.task_id,
                AuthorizationToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self._db.execute(
            update(AuthorizationToken)
            .where(AuthorizationToken.token == token)
            .values(used_note=note)
        )
        await self._db.flush()
