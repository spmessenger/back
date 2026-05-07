from typing import Annotated, TypeAlias
from fastapi import Depends
from core.services.room import YouTubeRoom
from core.repos.room import DbYouTubeRoomRepo


def get_youtube_room() -> YouTubeRoom:
    return YouTubeRoom(DbYouTubeRoomRepo())


YouTubeRoomDep: TypeAlias = Annotated[YouTubeRoom, Depends(get_youtube_room)]
