from dataclasses import dataclass
from datetime import datetime


@dataclass
class Session:
    id: str
    account_id: str
    platform: str
    session_key: str
    created_at: datetime
    last_active_at: datetime
    is_active: bool = True


@dataclass
class Message:
    id: str
    session_id: str
    role: str
    sender_id: str = ""
    sender_name: str = ""
    content: str = ""
    reasoning_content: str = ""
    token_count: int = 0
    created_at: datetime = None
