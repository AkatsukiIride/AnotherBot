from fastapi import APIRouter

from api.persona import router as persona_router
from api.provider import router as provider_router
from api.account import router as account_router
from api.sticker import router as sticker_router
from api.system import router as system_router

api_router = APIRouter()

api_router.include_router(persona_router, prefix="/personas", tags=["personas"])
api_router.include_router(provider_router, prefix="/providers", tags=["providers"])
api_router.include_router(account_router, prefix="/accounts", tags=["accounts"])
api_router.include_router(sticker_router, prefix="/stickers", tags=["stickers"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
