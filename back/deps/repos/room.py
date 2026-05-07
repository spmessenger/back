from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.room import AbstractYouTubeRoomRepo, DbYouTubeRoomRepo

YouTubeRoomRepoDep: TypeAlias = Annotated[AbstractYouTubeRoomRepo, Depends(DbYouTubeRoomRepo)]
