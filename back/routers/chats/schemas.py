from pydantic import BaseModel
from core.entities import Chat, Participant


class ChatCreation(BaseModel):
    chat: Chat
    participants: list[Participant]
