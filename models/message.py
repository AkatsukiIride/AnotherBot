from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class MessageType(Enum):
    GROUP = "group"
    PRIVATE = "private"


class MessageComponentType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AT = "at"


@dataclass
class MessageComponent:
    type: MessageComponentType
    data: dict


@dataclass
class MessageMember:
    user_id: str
    name: str


@dataclass
class AstrBotMessage:
    message_str: str
    message_chain: list[MessageComponent]
    type: MessageType
    session_id: str
    group_id: Optional[str] = None
    sender: Optional[MessageMember] = None
    is_at_bot: bool = False
    raw_message: Optional[dict] = None


@dataclass
class AstrMessageEvent:
    event_id: str
    account_id: str
    platform: str
    message: AstrBotMessage
    created_at: datetime = field(default_factory=datetime.now)
    stopped: bool = False

    def get_message_str(self) -> str:
        return self.message.message_str

    def stop_event(self):
        self.stopped = True
