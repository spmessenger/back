from pydantic import BaseModel
from core.entities import Chat, Participant


class ChatCreation(BaseModel):
    chat: Chat
    participants: list[Participant]


class AvailableUser(BaseModel):
    id: int
    username: str


class AvatarUpload(BaseModel):
    data_url: str
    stage_size: float
    crop_x: float
    crop_y: float
    crop_size: float


class GroupCreationRequest(BaseModel):
    title: str
    participants: list[int]
    avatar: AvatarUpload | None = None


class SendMessageRequest(BaseModel):
    content: str


class ChatMessageResponse(BaseModel):
    id: int
    chat_id: int
    content: str
    created_at_timestamp: float
    is_own: bool
