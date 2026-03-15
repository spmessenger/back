from __future__ import annotations

from io import BytesIO
from uuid import uuid4
import base64

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from back.settings import settings


def _parse_data_url(data_url: str) -> tuple[str, bytes]:
    header, encoded = data_url.split(',', 1)
    mime = header.split(';', 1)[0].split(':', 1)[1]
    return mime, base64.b64decode(encoded)


class S3StorageService:
    def __init__(self, client: BaseClient | None = None):
        self.client = client

    def _get_client(self) -> BaseClient:
        if self.client is None:
            self.client = boto3.client(
                's3',
                endpoint_url=settings.S3_ENDPOINT_URL,
                region_name=settings.S3_REGION,
                aws_access_key_id=settings.S3_ACCESS_KEY_ID,
                aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            )
        return self.client

    def ping_connection(self) -> bool:
        try:
            self._get_client().head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except (BotoCoreError, ClientError):
            return False
        return True

    def render_group_avatar_data_url(
        self,
        *,
        data_url: str,
        stage_size: float,
        crop_x: float,
        crop_y: float,
        crop_size: float,
    ) -> str:
        image_bytes = self._render_group_avatar_bytes(
            data_url=data_url,
            stage_size=stage_size,
            crop_x=crop_x,
            crop_y=crop_y,
            crop_size=crop_size,
        )
        encoded = base64.b64encode(image_bytes).decode('utf-8')
        return f'data:image/png;base64,{encoded}'

    def upload_group_avatar(
        self,
        *,
        data_url: str,
        stage_size: float,
        crop_x: float,
        crop_y: float,
        crop_size: float,
    ) -> str:
        image_bytes = self._render_group_avatar_bytes(
            data_url=data_url,
            stage_size=stage_size,
            crop_x=crop_x,
            crop_y=crop_y,
            crop_size=crop_size,
        )

        key = f'group-avatars/{uuid4().hex}.png'
        self._get_client().put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=image_bytes,
            ContentType='image/png',
        )
        return self._public_url(key)

    def _render_group_avatar_bytes(
        self,
        *,
        data_url: str,
        stage_size: float,
        crop_x: float,
        crop_y: float,
        crop_size: float,
    ) -> bytes:
        _, image_bytes = _parse_data_url(data_url)
        image = Image.open(BytesIO(image_bytes)).convert('RGBA')

        render_scale = min(stage_size / image.width, stage_size / image.height)
        render_width = image.width * render_scale
        render_height = image.height * render_scale
        image_left = (stage_size - render_width) / 2
        image_top = (stage_size - render_height) / 2

        src_x = round((crop_x - image_left) / render_scale)
        src_y = round((crop_y - image_top) / render_scale)
        src_x = min(max(0, src_x), max(0, image.width - 1))
        src_y = min(max(0, src_y), max(0, image.height - 1))
        src_size = max(1, round(crop_size / render_scale))
        src_size = min(src_size, image.width - src_x, image.height - src_y)

        cropped = image.crop((src_x, src_y, src_x + src_size, src_y + src_size))
        cropped = cropped.resize((280, 280), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        cropped.save(buffer, format='PNG')
        return buffer.getvalue()

    def _public_url(self, key: str) -> str:
        if settings.S3_PUBLIC_BASE_URL:
            return f"{settings.S3_PUBLIC_BASE_URL.rstrip('/')}/{key}"
        if settings.S3_ENDPOINT_URL:
            endpoint = settings.S3_ENDPOINT_URL.rstrip('/')
            return f"{endpoint}/{settings.S3_BUCKET_NAME}/{key}"
        return f"https://{settings.S3_BUCKET_NAME}.s3.{settings.S3_REGION}.amazonaws.com/{key}"
