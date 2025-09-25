from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .router import base_router

app = FastAPI()


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
