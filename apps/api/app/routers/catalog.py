from fastapi import APIRouter

from app.services.model_catalog import list_models_catalog

router = APIRouter()


@router.get("/api/models")
async def list_models():
    return await list_models_catalog()
