from fastapi import APIRouter
from .routers.auth import router as auth_router

base_router = APIRouter(
    prefix='/api'
)


base_router.include_router(auth_router)
