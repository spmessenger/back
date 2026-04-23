from __future__ import annotations

from io import BytesIO
from uuid import uuid4
import base64
import time
import re
from pathlib import Path
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from back.settings import settings


def _parse_data_url(data_url: str) -> tuple[str, bytes]:
    header, encoded = data_url.split(',', 1)
    mime = header.split(';', 1)[0].split(':', 1)[1]
    return mime, base64.b64decode(encoded)


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9._-]+', '-', filename).strip('-')
    return cleaned or 'file'


@dataclass
class AttachmentRecord:
    attachment_id: str
    storage_key: str
    original_name: str
    mime_type: str
    size_bytes: int
    status: str
    created_at: float
    local_path: str | None = None
    duration_seconds: float | None = None


class S3StorageService:
    _attachments_registry: dict[str, AttachmentRecord] = {}
    _local_attachments_root = Path(__file__).resolve().parents[2] / '.local_attachments'

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

    def init_attachment_upload(
        self,
        *,
        chat_id: int,
        filename: str,
        mime_type: str,
        size_bytes: int,
        expires_in: int = 900,
    ) -> dict[str, object]:
        attachment_id = uuid4().hex
        cleaned_name = _sanitize_filename(filename)
        storage_key = f'chat-attachments/{chat_id}/{attachment_id}-{cleaned_name}'

        upload_url = self._get_client().generate_presigned_url(
            'put_object',
            Params={
                'Bucket': settings.S3_BUCKET_NAME,
                'Key': storage_key,
                'ContentType': mime_type,
            },
            ExpiresIn=expires_in,
        )

        self._attachments_registry[attachment_id] = AttachmentRecord(
            attachment_id=attachment_id,
            storage_key=storage_key,
            original_name=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            status='pending',
            created_at=time.time(),
        )

        return {
            'attachment_id': attachment_id,
            'storage_key': storage_key,
            'upload_url': upload_url,
            'upload_method': 'PUT',
            'headers': {'Content-Type': mime_type},
            'expires_in': expires_in,
        }

    def complete_attachment_upload(
        self,
        attachment_id: str,
        *,
        duration_seconds: float | None = None,
    ) -> AttachmentRecord:
        record = self._attachments_registry.get(attachment_id)
        if record is None:
            raise ValueError('Attachment not found')

        if duration_seconds is not None:
            if duration_seconds < 0:
                raise ValueError('Attachment duration must be non-negative')
            record.duration_seconds = duration_seconds

        if record.local_path is not None:
            if not Path(record.local_path).exists():
                raise ValueError('Uploaded object is not available')
            record.status = 'ready'
            self._attachments_registry[attachment_id] = record
            return record

        try:
            self._get_client().head_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=record.storage_key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ValueError('Uploaded object is not available') from exc

        record.status = 'ready'
        self._attachments_registry[attachment_id] = record
        return record

    def upload_attachment_content(
        self,
        *,
        attachment_id: str,
        content: bytes,
        content_type: str | None = None,
    ) -> AttachmentRecord:
        record = self._attachments_registry.get(attachment_id)
        if record is None:
            raise ValueError('Attachment not found')

        if not content:
            raise ValueError('Attachment body is empty')

        # Browser upload transports can occasionally report a different client-side
        # file size than the received payload size (for example after platform-level
        # transformations). We trust the bytes we actually receive.
        received_size = len(content)
        if received_size <= 0:
            raise ValueError('Attachment body is empty')
        record.size_bytes = received_size

        resolved_content_type = (content_type or record.mime_type or 'application/octet-stream').strip()
        try:
            self._get_client().put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=record.storage_key,
                Body=content,
                ContentType=resolved_content_type,
            )
            record.local_path = None
        except (BotoCoreError, ClientError):
            self._local_attachments_root.mkdir(parents=True, exist_ok=True)
            local_path = self._local_attachments_root / (
                f'{record.attachment_id}-{_sanitize_filename(record.original_name)}'
            )
            local_path.write_bytes(content)
            record.local_path = str(local_path)

        self._attachments_registry[attachment_id] = record

        return record

    def get_attachment_record(self, attachment_id: str) -> AttachmentRecord | None:
        return self._attachments_registry.get(attachment_id)

    def get_local_attachment_path(self, attachment_id: str) -> str | None:
        record = self._attachments_registry.get(attachment_id)
        if record is None:
            return None
        return record.local_path

    def generate_attachment_download_url(self, *, storage_key: str, expires_in: int = 300) -> str:
        return self._get_client().generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.S3_BUCKET_NAME,
                'Key': storage_key,
            },
            ExpiresIn=expires_in,
        )

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

    def render_profile_avatar_data_url(
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
