from typing import AsyncGenerator
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.core.config import settings
from src.core.logging import logger

engine = create_async_engine(settings.database_url, echo=False)
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _sync_missing_columns(sync_conn) -> None:
    """Adiciona colunas novas em tabelas já existentes (equivalente a uma migração
    simples de "ADD COLUMN"). Este projeto não usa Alembic — `Base.metadata.create_all`
    só cria tabelas que ainda não existem, nunca altera as existentes (ver seção
    Database do CLAUDE.md). Isso cobre o caso mais comum ao evoluir os modelos ORM
    (uma coluna nova e nullable) sem exigir acesso manual ao arquivo do banco.
    Só roda para SQLite — é o único backend suportado neste projeto."""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(sync_conn)
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            if not column.nullable and column.server_default is None and column.default is None:
                # ALTER TABLE ADD COLUMN do SQLite exige NULL ou um default constante
                logger.warning(
                    f"Coluna '{column.name}' de '{table.name}' está faltando no banco mas "
                    "não é nullable nem tem default — não pode ser adicionada automaticamente."
                )
                continue
            col_type = column.type.compile(dialect=sync_conn.dialect)
            sync_conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
            logger.info(f"Coluna '{column.name}' adicionada à tabela '{table.name}' (migração automática)")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_missing_columns)
