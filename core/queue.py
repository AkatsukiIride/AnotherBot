import asyncio
import json
import uuid
from datetime import datetime

from storage.database import get_db


class MessageQueue:
    """SQLite persistent message queue"""

    async def enqueue(self, account_id: str, event) -> str:
        msg_id = str(uuid.uuid4())
        event_json = json.dumps({
            "event_id": event.event_id,
            "account_id": event.account_id,
            "platform": event.platform,
            "message": {
                "message_str": event.message.message_str,
                "type": event.message.type.value,
                "session_id": event.message.session_id,
                "group_id": event.message.group_id,
                "sender": {
                    "user_id": event.message.sender.user_id,
                    "name": event.message.sender.name,
                } if event.message.sender else None,
                "is_at_bot": event.message.is_at_bot,
                "raw_message": event.message.raw_message,
            },
            "created_at": event.created_at.isoformat(),
        }, ensure_ascii=False)

        db = get_db()
        db.execute(
            "INSERT INTO message_queue (id, account_id, event_json) VALUES (?, ?, ?)",
            (msg_id, account_id, event_json)
        )
        db.commit()
        db.close()
        return msg_id

    async def dequeue_batch(self, limit: int = 10) -> list[dict]:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM message_queue WHERE status='pending' ORDER BY created_at LIMIT ?",
            (limit,)
        ).fetchall()
        for row in rows:
            db.execute(
                "UPDATE message_queue SET status='processing', started_at=? WHERE id=?",
                (datetime.now().isoformat(), row['id'])
            )
        db.commit()
        result = [dict(r) for r in rows]
        db.close()
        return result

    async def mark_done(self, msg_id: str) -> None:
        db = get_db()
        db.execute(
            "UPDATE message_queue SET status='done', completed_at=? WHERE id=?",
            (datetime.now().isoformat(), msg_id)
        )
        db.commit()
        db.close()

    async def mark_failed(self, msg_id: str) -> None:
        db = get_db()
        db.execute(
            "UPDATE message_queue SET status='failed', retry_count=retry_count+1 WHERE id=?",
            (msg_id,)
        )
        db.commit()
        db.close()

    async def recover_on_startup(self) -> int:
        db = get_db()
        cursor = db.execute(
            "UPDATE message_queue SET status='pending' WHERE status IN ('pending','processing')"
        )
        db.commit()
        count = cursor.rowcount
        db.close()
        return count

    async def cleanup_old(self) -> int:
        db = get_db()
        cursor = db.execute(
            "DELETE FROM message_queue WHERE status='done' AND completed_at < datetime('now','-1 hour')"
        )
        db.commit()
        count = cursor.rowcount
        db.close()
        return count
