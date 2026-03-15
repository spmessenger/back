from typing import Annotated, TypeAlias
from fastapi import Depends

from back.services.storage import S3StorageService


def get_storage_service() -> S3StorageService:
    return S3StorageService()


StorageServiceDep: TypeAlias = Annotated[S3StorageService, Depends(get_storage_service)]
