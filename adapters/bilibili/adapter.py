"""Bilibili adapter — live danmaku + comments + private messages"""
import asyncio
import json
import logging
import os
import re
import time
import uuid

import httpx

from adapters.base import BaseAdapter
from models.message import (
    AstrMessageEvent, AstrBotMessage, MessageComponent,
    MessageType, MessageComponentType, MessageMember,
)

logger = logging.getLogger(__name__)


class BilibiliAdapter(BaseAdapter):
    """B站 unified adapter: live danmaku (viewer), comment replies, private messages"""

    def __init__(self, account_id: str, config: dict, queue):
        super().__init__(account_id, config, queue)
        self.sessdata = config.get('sessdata', '')
        self.bili_jct = config.get('bili_jct', '')
        self.buvid3 = config.get('buvid3', '')
        self.bot_name = config.get('bot_name', '')
        self.live_room_ids = config.get('live_room_ids', [])
        self.live_enabled = config.get('live_enabled', False)
        self.comment_enabled = config.get('comment_enabled', False)
        self.session_enabled = config.get('session_enabled', False)
        self._live_tasks = []
        self._comment_task = None
        self._session_task = None
        self._connected = False
        self._error = None
        self._replied_comments = self._load_replied_from_db()
        self._processed_msgs = {}

    def platform_name(self) -> str:
        return "bilibili"

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        try:
            cred = self._credential()
            if not cred.sessdata:
                self._error = "Cookie未配置"
                return

            if self.live_enabled and self.live_room_ids:
                for rid in self.live_room_ids:
                    task = asyncio.create_task(self._live_loop(rid))
                    self._live_tasks.append(task)
                logger.info(f"Bilibili live monitoring {len(self.live_room_ids)} room(s)")

            if self.comment_enabled:
                self._comment_task = asyncio.create_task(self._comment_loop())
                logger.info("Bilibili comment (@mention) monitoring started")

            if self.session_enabled:
                self._session_task = asyncio.create_task(self._session_loop())

            self._connected = True
        except Exception as e:
            self._error = str(e)
            logger.error(f"BilibiliAdapter start failed: {e}")

    async def stop(self) -> None:
        self._running = False
        for t in self._live_tasks:
            t.cancel()
        if self._comment_task:
            self._comment_task.cancel()
        if self._session_task:
            self._session_task.cancel()
        self._connected = False

    def status(self) -> dict:
        return {
            "platform": "bilibili",
            "bot_name": self.bot_name,
            "connected": self._connected,
            "error": self._error,
            "live_rooms": len(self._live_tasks),
            "running": self._running,
        }

    async def send(self, event: AstrMessageEvent,
                   reply_chain: list[MessageComponent]) -> bool:
        """Send reply. Route to correct channel based on event metadata."""
        raw = event.message.raw_message or {}
        source = raw.get('_bili_source', 'live')
        text = ''.join(c.data.get('text', '') for c in reply_chain if c.type == MessageComponentType.TEXT)
        logger.info(f'B站发送: source={source} text={text[:30]}...')
        if not text:
            return False
        try:
            if source == 'live':
                return await self._send_danmaku(event, text)
            elif source == 'comment':
                return await self._reply_comment(event, text)
            elif source == 'session':
                return await self._reply_session(event, text)
        except Exception as e:
            logger.error(f"Bilibili send failed: {e}")
            return False

    # ── Live Danmaku ───────────────────────────────────────

    async def _live_loop(self, room_id):
        fail_count = 0
        while self._running:
            try:
                from bilibili_api import live
                danmaku = live.LiveDanmaku(room_display_id=int(room_id), credential=self._credential())

                @danmaku.on("DANMU_MSG")
                async def on_danmaku(event):
                    try:
                        info = event.get('data', {}).get('info', [])
                        if len(info) < 3:
                            return
                        text = info[1]  # danmaku text
                        user_info = info[2]  # [uid, uname, ...]
                        uid = str(user_info[0]) if user_info else ''
                        uname = user_info[1] if len(user_info) > 1 else ''
                        logger.info(f'[DANMU] {uname}({uid}): {text[:30]}')
                        # Check @bot_name (also match @水泽晓 without space)
                        if self.bot_name not in text:
                            return
                        bili_event = AstrMessageEvent(
                            event_id=str(uuid.uuid4()),
                            account_id=self.account_id,
                            platform="bilibili",
                            message=AstrBotMessage(
                                message_str=text,
                                message_chain=[],
                                type=MessageType.GROUP,
                                session_id=f"live_{room_id}",
                                sender=MessageMember(user_id=uid, name=uname),
                                is_at_bot=True,
                                raw_message={'_bili_source': 'live', '_room_id': room_id},
                            ),
                        )
                        await self.queue.enqueue(self.account_id, bili_event)
                    except Exception:
                        pass

                @danmaku.on("LIVE")
                async def on_live(_):
                    logger.info(f"B站直播间 {room_id} 开播")

                self._connected = True
                self._error = None
                fail_count = 0
                logger.info(f"Bilibili live connected to room {room_id}")
                await danmaku.connect()
            except Exception as e:
                fail_count += 1
                if fail_count >= 3:
                    self._error = f"直播连接失败({fail_count}次): {e}"
                logger.error(f"Bilibili live room {room_id} failed (attempt {fail_count}): {e}")
                await asyncio.sleep(30)

    async def _send_danmaku(self, event, text: str) -> bool:
        """Send danmaku: clean action descriptions, limit to 2 chunks max"""
        D = 20
        # Strip parenthetical action descriptions like （掐灭烟头）
        import re
        text = re.sub(r'[（(][^）)]*[）)]', '', text)
        text = text.strip()
        # Only send first 2 chunks (40 chars) to avoid flooding
        chunks = [text[i:i+D] for i in range(0, min(len(text), D*2), D)]
        room_id = int(event.message.raw_message.get('_room_id', 0))
        try:
            from bilibili_api import live
            room = live.LiveRoom(room_display_id=room_id, credential=self._credential())
            for chunk in chunks:
                if chunk.strip():
                    await room.send_danmaku(live.Danmaku(chunk.strip()))
                    await asyncio.sleep(1.5)
            return True
        except Exception as e:
            logger.error(f"Send danmaku failed: {e}")
            return False

    # ── Comments (via @mention notifications) ──────────────

    async def _comment_loop(self):
        poller = AdaptivePoller()
        while self._running:
            await asyncio.sleep(poller.interval)
            logger.info(f"评论轮询: 检查@通知 (间隔{poller.interval}s)")
            try:
                found = await self._check_mentions()
                if found:
                    poller.on_activity()
                else:
                    poller.on_idle()
            except Exception as e:
                if '401' in str(e) or '403' in str(e):
                    self._error = "Cookie已过期"
                logger.error(f"Comment poll error: {e}")

    async def _check_mentions(self) -> bool:
        """Poll B站 @mention notifications - check unread count first"""
        found_any = False
        authorized_uids = set(self.config.get('authorized_uids', []))
        try:
            from bilibili_api import session
            # Quick check: skip if no unread @mentions
            unread = await session.get_unread_messages(credential=self._credential())
            at_count = unread.get('at', 0)
            if at_count == 0:
                logger.debug('无新的@提及')
                return False
            logger.info(f'有{at_count}条未读@提及')

            data = await session.get_at(credential=self._credential())
            items = data.get('items', [])
            for item in items:
                item_id = str(item.get('id', ''))
                if item_id in self._replied_comments:
                    continue
                self._replied_comments.add(item_id)
                self._save_replied_to_db(item_id)
                user_info = item.get('user', {})
                uid = str(user_info.get('mid', ''))
                uname = user_info.get('nickname', '')
                if uid not in authorized_uids:
                    continue

                # get_at returns nested item structure
                inner = item.get('item', {})
                content = inner.get('source_content', '')  # Actual @mention text
                oid = str(inner.get('subject_id', ''))     # Correct oid for reply
                rpid = str(inner.get('source_id', ''))    # Comment rpid to reply to
                biz_id = inner.get('business_id', 1)       # Comment resource type

                if not content or not oid:
                    continue

                logger.info(f'[@提及] {uname}({uid}): {content[:50]}')

                bili_event = AstrMessageEvent(
                    event_id=str(uuid.uuid4()),
                    account_id=self.account_id,
                    platform="bilibili",
                    message=AstrBotMessage(
                        message_str=content,
                        message_chain=[],
                        type=MessageType.GROUP,
                        session_id=f"comment_{oid}",
                        sender=MessageMember(user_id=uid, name=uname),
                        is_at_bot=True,
                        raw_message={'_bili_source': 'comment',
                                     '_oid': oid, '_biz_type': biz_id, '_rpid': rpid},
                    ),
                )
                await self.queue.enqueue(self.account_id, bili_event)
                found_any = True
        except Exception as e:
            if '401' in str(e) or '403' in str(e):
                self._error = "Cookie已过期"
            logger.debug(f"Mention check error: {e}")
        return found_any

    async def _reply_comment(self, event, text: str) -> bool:
        try:
            from bilibili_api import comment
            raw = event.message.raw_message or {}
            oid = raw.get('_oid', '')
            rpid = raw.get('_rpid')
            biz_type = raw.get('_biz_type', 1)
            try:
                ctype = comment.CommentResourceType(biz_type)
            except Exception:
                ctype = comment.CommentResourceType.VIDEO
            kwargs = dict(text=text, credential=self._credential())
            kwargs['oid'] = int(oid) if oid.isdigit() else str(oid)
            kwargs['type_'] = ctype
            if rpid:
                kwargs['root'] = int(rpid)
                kwargs['parent'] = int(rpid)
            await comment.send_comment(**kwargs)
            logger.info(f"评论回复成功: oid={oid} rpid={rpid}")
            return True
        except Exception as e:
            logger.error(f"Reply comment failed: {e}")
            return False

    # ── Private Messages ────────────────────────────────────

    async def _session_loop(self):
        while self._running:
            try:
                from bilibili_api import session
                sess = session.Session(credential=self._credential())

                @sess.on(session.EventType.TEXT)
                async def on_text(ev):
                    try:
                        uid = str(getattr(ev, 'sender_uid', ''))
                        content = getattr(ev, 'content', '')
                        uname = getattr(ev, 'uname', '')
                        if not uid or not content:
                            return
                        # Dedup: skip if same uid+content already processed
                        msg_key = f"{uid}:{content}"
                        if msg_key in self._processed_msgs:
                            return
                        self._processed_msgs[uid] = content
                        logger.info(f'[私信] {uname}({uid}): {content[:40]}')
                        bili_event = AstrMessageEvent(
                            event_id=str(uuid.uuid4()),
                            account_id=self.account_id,
                            platform="bilibili",
                            message=AstrBotMessage(
                                message_str=content,
                                message_chain=[],
                                type=MessageType.PRIVATE,
                                session_id=f"session_{uid}",
                                sender=MessageMember(user_id=uid, name=uname),
                                is_at_bot=True,
                                raw_message={'_bili_source': 'session', '_uid': uid},
                            ),
                        )
                        await self.queue.enqueue(self.account_id, bili_event)
                    except Exception:
                        pass

                logger.info("Bilibili session monitoring started")
                self._error = None
                await sess.start()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if '401' in str(e) or '403' in str(e):
                    self._error = "Cookie已过期"
                logger.error(f"Session loop error: {e}")
                await asyncio.sleep(30)

    async def _reply_session(self, event, text: str) -> bool:
        try:
            from bilibili_api import session
            uid = int(event.message.sender.user_id)
            await session.send_msg(
                credential=self._credential(),
                receiver_id=uid,
                msg_type=session.EventType.TEXT,
                content=text,
            )
            return True
        except Exception as e:
            logger.error(f"Reply session failed: {e}")
            return False

    # ── Persistence ─────────────────────────────────────────

    def _load_replied_from_db(self) -> set:
        try:
            from storage.database import get_db
            db = get_db()
            rows = db.execute("SELECT item_id FROM bili_replied").fetchall()
            db.close()
            return {r['item_id'] for r in rows}
        except Exception:
            return set()

    def _save_replied_to_db(self, item_id: str):
        try:
            from storage.database import get_db
            db = get_db()
            db.execute("INSERT OR IGNORE INTO bili_replied (item_id) VALUES (?)", (item_id,))
            db.commit()
            db.close()
        except Exception:
            pass

    # ── Auth ────────────────────────────────────────────────

    def _credential(self):
        from bilibili_api import Credential
        return Credential(sessdata=self.sessdata, bili_jct=self.bili_jct, buvid3=self.buvid3)


# ── Adaptive Poller ────────────────────────────────────────

class AdaptivePoller:
    SLOW = 600      # 10 min
    FAST = 60       # 1 min
    IDLE_TIMEOUT = 300  # 5 min → back to slow

    def __init__(self):
        self.interval = self.SLOW
        self.last_at_time = 0.0

    def on_activity(self):
        self.last_at_time = time.time()
        self.interval = self.FAST

    def on_idle(self):
        if self.interval == self.FAST and time.time() - self.last_at_time > self.IDLE_TIMEOUT:
            self.interval = self.SLOW
