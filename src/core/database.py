from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.core.config import settings

# pool_pre_ping evita erros de "connection closed" quando o Postgres gerenciado
# (Railway) derruba conexões ociosas — sem custo perceptível para SQLite local.
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _):
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")  # aguarda até 30s se o DB estiver bloqueado
    cursor.close()


class Base(DeclarativeBase):
    pass


def db_insert(table):
    """Retorna o construct de INSERT com suporte a ON CONFLICT (upsert) correto
    para o dialeto configurado (sqlite localmente, postgresql em produção).
    Os dois dialetos aceitam a mesma sintaxe de on_conflict_do_update(index_elements=...),
    então os call sites não precisam saber qual dialeto está ativo."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        return pg_insert(table)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    return sqlite_insert(table)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
