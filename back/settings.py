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
    YOUTUBE_ASSISTED_FEATURE_ENABLED: bool = False
    YOUTUBE_ASSISTED_PREMIUM_USERNAMES: str = ''
    YOUTUBE_ASSIST_PROXY_ALLOWED_HOSTS: str = (
        'youtube.com,youtu.be,youtube-nocookie.com,ytimg.com,googlevideo.com,youtubei.googleapis.com,ggpht.com'
    )
    YOUTUBE_ASSIST_PROXY_TIMEOUT_SECONDS: float = 25.0

    model_config = ConfigDict(extra='ignore')


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
