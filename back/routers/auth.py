from fastapi import APIRouter
from .deps import AuthServiceDep

router = APIRouter()


@router.post('/login')
async def login(service: AuthServiceDep):
    return {'status': 'ok'}
