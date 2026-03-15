from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.session import ping_connection
from db.settings import settings, DatabaseTypeEnum
from db.misc import create_tables, drop_tables, ensure_tables_exist
from .router import base_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DB_TYPE == DatabaseTypeEnum.IN_MEMORY:
        create_tables()
    if not ping_connection():
        raise RuntimeError('Database connection failed during application startup')
    ensure_tables_exist()
    yield
    if settings.DB_TYPE == DatabaseTypeEnum.IN_MEMORY:
        drop_tables()

app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/health')
async def health():
    return {'status': 'ok'}


app.include_router(base_router)
