from enum import StrEnum
from pydantic_settings import BaseSettings
from functools import lru_cache


class RepoImplType(StrEnum):
    MEMORY = 'memory'
    DB = 'db'


class Settings(BaseSettings):
    REPO_IMPL_TYPE: RepoImplType = RepoImplType.MEMORY


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
