from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.session import ping_connection
from db.settings import get_settings, DatabaseTypeEnum
from db.misc import create_tables, drop_tables, ensure_tables_exist
from .services.ws_manager import WebSocketConnectionManager
from .services.storage import S3StorageService
from .router import base_router

settings = get_settings()
logger = logging.getLogger('uvicorn.error')
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DB_TYPE == DatabaseTypeEnum.IN_MEMORY:
        create_tables()
    if not ping_connection():
        raise RuntimeError(
            'Database connection failed during application startup')
    ensure_tables_exist()

    storage = S3StorageService()
    app.state.s3_available = storage.ping_connection()
    if app.state.s3_available:
        logger.info('S3/MinIO connection is available at startup.')
    else:
        logger.warning(
            'S3/MinIO is not reachable at startup. Local attachment fallback will be used.')

    yield
    if settings.DB_TYPE == DatabaseTypeEnum.IN_MEMORY:
        drop_tables()

app = FastAPI(lifespan=lifespan)
app.state.ws_manager = WebSocketConnectionManager()


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$',
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/health')
async def health():
    return {'status': 'ok'}


app.include_router(base_router)
