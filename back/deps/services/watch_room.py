from typing import Annotated, TypeAlias
from fastapi import Depends

from back.services.watch_room import WatchRoomService


def get_watch_room_service() -> WatchRoomService:
    return WatchRoomService()


WatchRoomServiceDep: TypeAlias = Annotated[WatchRoomService, Depends(get_watch_room_service)]
