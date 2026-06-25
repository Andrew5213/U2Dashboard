from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.repositories.cache_repository import CacheRepository

router = APIRouter(prefix="/disciplines", tags=["disciplines"])


class WeightEntry(BaseModel):
    list_id: str
    weight: float

    @field_validator("weight")
    @classmethod
    def weight_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("weight deve estar entre 0.0 e 1.0")
        return round(v, 6)


class SetWeightsBody(BaseModel):
    weights: list[WeightEntry]

    @field_validator("weights")
    @classmethod
    def weights_sum(cls, v: list[WeightEntry]) -> list[WeightEntry]:
        total = sum(e.weight for e in v)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Pesos devem somar 1.0 (100%); soma atual: {total:.4f}")
        return v


@router.get("/folder/{folder_id}", summary="Pesos e progresso ponderado de uma pasta")
async def get_disciplines(folder_id: str, db: AsyncSession = Depends(get_db)):
    repo = CacheRepository(db)
    data = await repo.get_weighted_progress(folder_id)
    return JSONResponse({"success": True, "data": data})


@router.post("/folder/{folder_id}", summary="Salvar pesos das disciplinas de uma pasta")
async def set_disciplines(
    folder_id: str,
    body: SetWeightsBody,
    db: AsyncSession = Depends(get_db),
):
    repo = CacheRepository(db)
    # Valida que todos os list_ids pertencem a esta pasta
    all_lists = await repo.get_lists_with_metrics(folder_id)
    valid_ids = {l["list_id"] for l in all_lists}
    for entry in body.weights:
        if entry.list_id not in valid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"list_id '{entry.list_id}' não pertence à pasta {folder_id}",
            )
    await repo.set_discipline_weights({e.list_id: e.weight for e in body.weights})
    data = await repo.get_weighted_progress(folder_id)
    return JSONResponse({"success": True, "data": data})


@router.delete("/folder/{folder_id}", summary="Remover pesos configurados de uma pasta")
async def delete_disciplines(folder_id: str, db: AsyncSession = Depends(get_db)):
    repo = CacheRepository(db)
    await repo.delete_discipline_weights(folder_id)
    return JSONResponse({"success": True})
