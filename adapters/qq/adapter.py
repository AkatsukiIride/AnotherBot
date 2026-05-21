import json
import os
import uuid
import logging
from collections import OrderedDict

import websockets

from adapters.base import BaseAdapter
from models.message import (
    AstrMessageEvent, AstrBotMessage, MessageComponent,
    MessageType, MessageComponentType, MessageMember,
)

logger = logging.getLogger(__name__)


class QQAdapter(BaseAdapter):
    """QQ platform adapter via OneBot v11 reverse WebSocket"""

    def __init__(self, account_id: str, config: dict, queue):
        super().__init__(account_id, config, queue)
        self.ws_port = config.get('ws_port', 3001)
        self.bot_qq = config.get('bot_qq', '')
        self._server = None
        self._client = None
        # Recall: user_msg_id → (bot_msg_id, group_id|None)
        self._replied_ids: OrderedDict[str, tuple[int, str | None]] = OrderedDict()
        # Echo callbacks for async API response handling
        self._echo_callbacks: dict[str, callable] = {}

    def platform_name(self) -> str:
        return "qq"

    async def start(self) -> None:
        self._running = True
        self._server = await websockets.serve(
            self._handle_connection,
            "127.0.0.1", self.ws_port
        )
        logger.info(f"QQAdapter WS server listening on :{self.ws_port}")

    async def _handle_connection(self, ws):
        self._client = ws
        logger.info("NapCat client connected")
        self._broadcast_status("connected")
        try:
            async for raw in ws:
                if not self._running:
                    break
                data = json.loads(raw)
                # API response (has echo/status, no post_type)
                if 'post_type' not in data and 'echo' in data:
                    cb = self._echo_callbacks.pop(data['echo'], None)
                    if cb:
                        cb(data)
                    continue
                post_type = data.get('post_type', '')
                if post_type == 'message':
                    event = self._to_event(data)
                    await self.queue.enqueue(self.account_id, event)
                elif post_type == 'notice':
                    await self._on_notice(data)
                # meta_event → heartbeat, ignored
        except websockets.exceptions.ConnectionClosed:
            logger.warning("NapCat client disconnected")
        finally:
            self._client = None
            self._broadcast_status("connecting")

    async def _on_notice(self, data: dict):
        """Handle recall: if bot already replied, withdraw its reply."""
        notice_type = data.get('notice_type', '')
        if notice_type not in ('group_recall', 'friend_recall'):
            return
        user_msg_id = str(data.get('message_id', ''))
        if not user_msg_id:
            return

        bot_info = self._replied_ids.pop(user_msg_id, None)
        if bot_info and self._client:
            bot_msg_id, group_id = bot_info
            try:
                await self._client.send(json.dumps({
                    "action": "delete_msg",
                    "params": {"message_id": bot_msg_id}
                }, ensure_ascii=False))
                logger.info(f"Withdrew bot reply {bot_msg_id} for recalled msg {user_msg_id}")
            except Exception:
                pass

    def _broadcast_status(self, status: str):
        try:
            from api.system import broadcast_event
            broadcast_event("status", {
                "account_id": self.account_id,
                "status": status,
            })
        except Exception:
            pass

    def _to_event(self, data: dict) -> AstrMessageEvent:
        is_group = data.get('message_type') == 'group'
        msg_type = MessageType.GROUP if is_group else MessageType.PRIVATE
        group_id = str(data.get('group_id', ''))

        message_str = ""
        is_at = False
        image_url = None
        components = []

        for seg in data.get('message', []):
            seg_type = seg.get('type', '')
            seg_data = seg.get('data', {})
            if seg_type == 'text':
                text = seg_data.get('text', '').strip()
                message_str += text
                components.append(MessageComponent(MessageComponentType.TEXT, seg_data))
            elif seg_type == 'at':
                if seg_data.get('qq') == self.bot_qq:
                    is_at = True
                components.append(MessageComponent(MessageComponentType.AT, seg_data))
            elif seg_type == 'image':
                if not image_url:
                    image_url = seg_data.get('url', '')
                components.append(MessageComponent(MessageComponentType.IMAGE, seg_data))

        session_key = f"group_{group_id}" if is_group else f"private_{data.get('user_id', '')}"

        sender_info = data.get('sender', {})
        sender = MessageMember(
            user_id=str(data.get('user_id', '')),
            name=sender_info.get('card') or sender_info.get('nickname', '')
        )

        return AstrMessageEvent(
            event_id=str(uuid.uuid4()),
            account_id=self.account_id,
            platform="qq",
            message=AstrBotMessage(
                message_str=message_str,
                message_chain=components,
                type=msg_type,
                session_id=session_key,
                group_id=group_id if is_group else None,
                sender=sender,
                is_at_bot=is_at,
                image_url=image_url,
                raw_message=data,
            )
        )

    async def send(self, event: AstrMessageEvent,
                   reply_chain: list[MessageComponent]) -> bool:
        if not self._client:
            logger.warning("QQAdapter: no client connected, cannot send")
            return False

        onebot_chain = []
        at_sender = False
        for comp in reply_chain:
            if comp.type == MessageComponentType.TEXT:
                if event.message.type == MessageType.GROUP and not at_sender:
                    onebot_chain.append({
                        "type": "at",
                        "data": {"qq": event.message.sender.user_id}
                    })
                    at_sender = True
                onebot_chain.append({
                    "type": "text",
                    "data": {"text": comp.data.get('text', '')}
                })
            elif comp.type == MessageComponentType.IMAGE:
                file_path = comp.data.get('file', '')
                if file_path:
                    file_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
                onebot_chain.append({
                    "type": "image",
                    "data": {"file": file_path}
                })

        if event.message.type == MessageType.GROUP:
            action = "send_group_msg"
            params = {"group_id": int(event.message.group_id), "message": onebot_chain}
        else:
            action = "send_private_msg"
            params = {
                "user_id": int(event.message.sender.user_id),
                "message": onebot_chain
            }

        echo = str(uuid.uuid4())[:8]
        payload = {"action": action, "params": params, "echo": echo}

        # Register callback to capture bot message_id for recall tracking
        user_msg_id = str(event.message.raw_message.get('message_id', ''))
        if user_msg_id:
            def _on_response(resp: dict):
                bot_msg_id = resp.get('data', {}).get('message_id', 0)
                if bot_msg_id:
                    self._replied_ids[user_msg_id] = (
                        int(bot_msg_id), event.message.group_id)
                    if len(self._replied_ids) > 200:
                        self._replied_ids.popitem(last=False)
            self._echo_callbacks[echo] = _on_response

        try:
            await self._client.send(json.dumps(payload, ensure_ascii=False))
            return True
        except websockets.exceptions.ConnectionClosed:
            self._echo_callbacks.pop(echo, None)
            logger.error("QQAdapter: send failed, connection closed")
            return False

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def status(self) -> dict:
        connected = False
        if self._client is not None and self._running:
            try:
                connected = self._client.state.name == 'OPEN'
            except Exception:
                connected = False
        return {
            "platform": "qq",
            "bot_qq": self.bot_qq,
            "ws_port": self.ws_port,
            "connected": connected,
            "running": self._running,
        }
