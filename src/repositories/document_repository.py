from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document_models import Document


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, data: dict) -> Document:
        doc = Document(**data)
        self._db.add(doc)
        await self._db.flush()
        return doc

    async def get(self, document_id: int) -> Document | None:
        result = await self._db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def list(self, folder_id: str | None = None) -> list[Document]:
        stmt = select(Document).order_by(Document.uploaded_at.desc())
        if folder_id:
            stmt = stmt.where(Document.folder_id == folder_id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, document_id: int) -> bool:
        result = await self._db.execute(delete(Document).where(Document.id == document_id))
        return result.rowcount > 0
