from pydantic import BaseModel
from pydantic import model_validator
from core.entities import Chat, Participant
from typing import Literal


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


class WsChatActionRequest(BaseModel):
    action: Literal['get_messages', 'send_message']
    chat_id: int
    content: str | None = None
    client_message_id: str | None = None

    @model_validator(mode='after')
    def validate_content_for_send(self) -> 'WsChatActionRequest':
        if self.action == 'send_message' and not self.content:
            raise ValueError('content is required for send_message action')
        return self
