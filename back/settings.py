from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic import ConfigDict


class Settings(BaseSettings):
    S3_ENDPOINT_URL: str | None = 'http://localhost:9000'
    S3_REGION: str = 'us-east-1'
    S3_BUCKET_NAME: str = 'spmessenger'
    S3_ACCESS_KEY_ID: str = 'minioadmin'
    S3_SECRET_ACCESS_KEY: str = 'minioadmin'
    S3_PUBLIC_BASE_URL: str | None = 'http://localhost:9000/spmessenger'

    model_config = ConfigDict(extra='ignore')


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
