import os
import secrets

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.core.logging import logger
from src.repositories.cache_repository import CacheRepository
from src.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])

_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


@router.get("/folders", summary="Listar províncias disponíveis para associar documentos")
async def list_document_folders(
    space_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    sid = space_id or settings.clickup_default_space_id
    if not sid:
        raise HTTPException(status_code=400, detail="space_id é obrigatório")
    folders = await CacheRepository(db).get_all_folders(sid)
    return JSONResponse([{"folder_id": f.folder_id, "name": f.name} for f in folders])


@router.get("", summary="Listar documentos")
async def list_documents(
    folder_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    docs = await DocumentService(db).list_documents(folder_id)
    return JSONResponse(docs)


@router.post("", status_code=201, summary="Enviar documento PDF")
async def upload_document(
    folder_id: str = Form(...),
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são permitidos")

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_SIZE:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (máx 50 MB)")

    folder = await CacheRepository(db).get_folder_by_id(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Província não encontrada")

    try:
        doc = await DocumentService(db).upload_document(
            folder_id=folder_id,
            folder_name=folder.name,
            file_bytes=file_bytes,
            original_filename=file.filename or "documento.pdf",
            description=description,
            docs_dir=settings.documents_dir,
        )
        await db.commit()
        return doc
    except Exception as exc:
        logger.error(f"Erro ao salvar documento: {exc}")
        raise HTTPException(status_code=500, detail="Erro ao salvar documento")


@router.get("/{document_id}/download", summary="Baixar documento")
async def download_document(document_id: int, db: AsyncSession = Depends(get_db)):
    doc = await DocumentService(db).get_document_for_download(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    file_path = os.path.join(settings.documents_dir, doc.stored_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no armazenamento")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=doc.original_filename,
    )


@router.delete("/{document_id}", summary="Excluir documento")
async def delete_document(
    document_id: int,
    x_delete_password: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not secrets.compare_digest(x_delete_password, settings.documents_delete_password):
        raise HTTPException(status_code=403, detail="Senha incorreta")
    deleted = await DocumentService(db).delete_document(document_id, settings.documents_dir)
    if not deleted:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    await db.commit()
    return {"success": True}
