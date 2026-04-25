from typing import Annotated, TypeAlias
from fastapi import Depends

from back.services.live_location import LiveLocationService


def get_live_location_service() -> LiveLocationService:
    return LiveLocationService()


LiveLocationServiceDep: TypeAlias = Annotated[LiveLocationService, Depends(get_live_location_service)]
