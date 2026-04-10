from typing import Annotated, TypeAlias
from fastapi import Depends
from core.services.messenger import MessengerService
from ..repos import ChatRepoDep, ChatGroupRepoDep, ParticipantRepoDep, MessageRepoDep, UserRepoDep


def get_messenger_service(chat_repo: ChatRepoDep, participant_repo: ParticipantRepoDep,
                          message_repo: MessageRepoDep, user_repo: UserRepoDep,
                          chat_group_repo: ChatGroupRepoDep) -> MessengerService:
    return MessengerService(chat_repo, participant_repo, message_repo, user_repo, chat_group_repo)


MessengerServiceDep: TypeAlias = Annotated[MessengerService, Depends(get_messenger_service)]
