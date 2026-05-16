from abc import ABC, abstractmethod

from models.message import AstrMessageEvent, MessageComponent


class BaseAdapter(ABC):
    """Platform adapter base class — one instance per account"""

    def __init__(self, account_id: str, config: dict, queue):
        self.account_id = account_id
        self.config = config
        self.queue = queue
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start listening for platform messages"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and disconnect"""
        ...

    @abstractmethod
    async def send(self, event: AstrMessageEvent,
                   reply_chain: list[MessageComponent]) -> bool:
        """Send reply back to platform"""
        ...

    @abstractmethod
    def platform_name(self) -> str:
        """Return platform identifier"""
        ...

    @abstractmethod
    def status(self) -> dict:
        """Return connection status info"""
        ...
