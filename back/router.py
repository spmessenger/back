from fastapi import APIRouter
from .routers.auth import router as auth_router
from .routers.chats import router as chats_router
from .routers.rooms import router as rooms_router

base_router = APIRouter(
    prefix='/api'
)


base_router.include_router(auth_router)
base_router.include_router(chats_router)
base_router.include_router(rooms_router)
