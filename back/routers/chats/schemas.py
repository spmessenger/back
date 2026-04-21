from pydantic import BaseModel, Field
from pydantic import model_validator
from core.entities import Chat, Participant
from typing import Literal
from back.schemas import AvatarUpload


class ChatCreation(BaseModel):
    chat: Chat
    participants: list[Participant]


class AvailableUser(BaseModel):
    id: int
    username: str
    avatar_url: str | None = None


class GroupCreationRequest(BaseModel):
    title: str
    participants: list[int]
    avatar: AvatarUpload | None = None


class SendMessageRequest(BaseModel):
    content: str
    content_type: Literal['text', 'image', 'video', 'document'] | None = None
    attachment_id: str | None = None
    attachment_group_id: str | None = None
    reference_message_id: int | None = None
    forwarded_from_message_id: int | None = None


class ChatAttachmentResponse(BaseModel):
    id: str
    original_name: str
    mime_type: str
    size_bytes: int
    download_url: str | None = None
    status: Literal['pending', 'ready', 'failed'] = 'ready'


class ChatMessageResponse(BaseModel):
    id: int
    chat_id: int
    reference_message_id: int | None = None
    reference_author: str | None = None
    reference_content: str | None = None
    forwarded_from_message_id: int | None = None
    forwarded_from_author: str | None = None
    forwarded_from_author_avatar_url: str | None = None
    forwarded_from_content: str | None = None
    content: str
    content_type: Literal['text', 'image', 'video', 'document'] = 'text'
    attachment: ChatAttachmentResponse | None = None
    attachment_group_id: str | None = None
    created_at_timestamp: float
    is_own: bool


class WsChatActionRequest(BaseModel):
    action: Literal['get_messages', 'send_message']
    chat_id: int
    content: str | None = None
    reference_message_id: int | None = None
    forwarded_from_message_id: int | None = None
    client_message_id: str | None = None
    before_message_id: int | None = None
    limit: int | None = 50

    @model_validator(mode='after')
    def validate_content_for_send(self) -> 'WsChatActionRequest':
        if self.action == 'send_message' and not self.content:
            raise ValueError('content is required for send_message action')
        return self


class ChatGroupResponse(BaseModel):
    id: int
    title: str
    chat_ids: list[int]


class ChatGroupReplaceItem(BaseModel):
    title: str
    chat_ids: list[int] = Field(default_factory=list)


class ReplaceChatGroupsRequest(BaseModel):
    groups: list[ChatGroupReplaceItem]


class AttachmentInitRequest(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)


class AttachmentInitResponse(BaseModel):
    attachment_id: str
    storage_key: str
    upload_url: str
    upload_method: Literal['PUT', 'POST']
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int


class AttachmentCompleteRequest(BaseModel):
    sha256: str | None = None


class AttachmentCompleteResponse(BaseModel):
    attachment_id: str
    status: Literal['pending', 'ready', 'failed']
    mime_type: str
    size_bytes: int


class AttachmentDownloadResponse(BaseModel):
    url: str
    expires_in: int


class LinkPreviewResponse(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    site_name: str | None = None
    youtube_video_id: str | None = None


class WatchRoomCreateRequest(BaseModel):
    chat_id: int
    youtube_video_id: str


class WatchRoomSyncRequest(BaseModel):
    current_time_seconds: float = 0.0
    is_playing: bool = True


class WatchRoomInviteRequest(BaseModel):
    target_user_id: int
    target_chat_id: int | None = None


class WatchRoomInviteResponse(BaseModel):
    id: str
    room_id: str
    from_user_id: int
    from_username: str
    to_user_id: int
    source_chat_id: int
    target_chat_id: int | None = None
    youtube_video_id: str
    status: Literal['pending', 'accepted', 'declined']
    created_at: float


class WatchRoomResponse(BaseModel):
    id: str
    chat_id: int
    youtube_video_id: str
    host_user_id: int
    viewer_user_ids: list[int]
    viewer_count: int
    sync_revision: int
    sync_current_time_seconds: float
    sync_is_playing: bool
    created_at: float
