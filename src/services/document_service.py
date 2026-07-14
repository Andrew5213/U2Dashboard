import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.document_repository import DocumentRepository


def _to_dict(doc) -> dict:
    return {
        "id": doc.id,
        "folder_id": doc.folder_id,
        "folder_name": doc.folder_name,
        "original_filename": doc.original_filename,
        "file_size": doc.file_size,
        "description": doc.description,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
    }


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = DocumentRepository(db)

    async def list_documents(self, folder_id: str | None = None) -> list[dict]:
        docs = await self._repo.list(folder_id)
        return [_to_dict(d) for d in docs]

    async def upload_document(
        self,
        folder_id: str,
        folder_name: str,
        file_bytes: bytes,
        original_filename: str,
        description: str | None,
        docs_dir: str,
    ) -> dict:
        stored_filename = f"{uuid.uuid4().hex}.pdf"
        os.makedirs(docs_dir, exist_ok=True)
        with open(os.path.join(docs_dir, stored_filename), "wb") as fh:
            fh.write(file_bytes)

        doc = await self._repo.create({
            "folder_id": folder_id,
            "folder_name": folder_name,
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "file_size": len(file_bytes),
            "description": description,
        })
        return _to_dict(doc)

    async def get_document_for_download(self, document_id: int):
        return await self._repo.get(document_id)

    async def delete_document(self, document_id: int, docs_dir: str) -> bool:
        doc = await self._repo.get(document_id)
        if not doc:
            return False
        file_path = os.path.join(docs_dir, doc.stored_filename)
        deleted = await self._repo.delete(document_id)
        if deleted and os.path.exists(file_path):
            os.remove(file_path)
        return deleted
