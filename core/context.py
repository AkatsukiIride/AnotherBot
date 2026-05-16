import uuid
from datetime import datetime, timedelta

from storage.database import get_db
from models.session import Session, Message


class ContextManager:
    """Session context manager with sliding window"""

    async def get_or_create_session(
        self, account_id: str, platform: str, session_key: str
    ) -> Session:
        db = get_db()
        row = db.execute(
            "SELECT * FROM sessions WHERE account_id=? AND platform=? AND session_key=? AND is_active=1",
            (account_id, platform, session_key)
        ).fetchone()

        if row:
            db.execute(
                "UPDATE sessions SET last_active_at=? WHERE id=?",
                (datetime.now().isoformat(), row['id'])
            )
            db.commit()
            db.close()
            return Session(**dict(row))

        # Clean up any inactive session with same key (from /new)
        db.execute(
            "DELETE FROM sessions WHERE account_id=? AND platform=? AND session_key=? AND is_active=0",
            (account_id, platform, session_key)
        )

        sid = str(uuid.uuid4())
        now = datetime.now().isoformat()
        db.execute(
            "INSERT INTO sessions (id, account_id, platform, session_key, created_at, last_active_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, account_id, platform, session_key, now, now)
        )
        db.commit()
        db.close()
        return Session(id=sid, account_id=account_id, platform=platform,
                       session_key=session_key, created_at=datetime.now(),
                       last_active_at=datetime.now(), is_active=True)

    async def build_context(
        self, session: Session, max_turns: int, ttl_minutes: int
    ) -> list[Message]:
        db = get_db()
        cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
        rows = db.execute(
            "SELECT * FROM messages WHERE session_id=? AND created_at > ? ORDER BY created_at",
            (session.id, cutoff)
        ).fetchall()
        db.close()

        messages = []
        for r in rows:
            d = dict(r)
            d['created_at'] = datetime.fromisoformat(d['created_at'])
            messages.append(Message(**d))
        return messages[-(max_turns * 2):]

    async def add_message_with_reasoning(self, session: Session, role: str,
                                          content: str, reasoning: str = "",
                                          sender_id: str = "", sender_name: str = "",
                                          token_count: int = 0) -> str:
        msg_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        db = get_db()
        db.execute(
            "INSERT INTO messages (id, session_id, role, sender_id, sender_name, content, reasoning_content, token_count, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (msg_id, session.id, role, sender_id, sender_name, content, reasoning, token_count, now)
        )
        db.execute(
            "UPDATE sessions SET last_active_at=? WHERE id=?",
            (now, session.id)
        )
        db.commit()
        db.close()
        return msg_id

    async def add_message(self, session: Session, role: str, content: str,
                          sender_id: str = "", sender_name: str = "") -> str:
        msg_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        db = get_db()
        db.execute(
            "INSERT INTO messages (id, session_id, role, sender_id, sender_name, content, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (msg_id, session.id, role, sender_id, sender_name, content, now)
        )
        db.execute(
            "UPDATE sessions SET last_active_at=? WHERE id=?",
            (now, session.id)
        )
        db.commit()
        db.close()
        return msg_id

    async def end_session(self, account_id: str, platform: str, session_key: str) -> None:
        """Mark session as inactive without deleting (for /new command)"""
        db = get_db()
        db.execute(
            "UPDATE sessions SET is_active=0 WHERE account_id=? AND platform=? AND session_key=?",
            (account_id, platform, session_key)
        )
        db.commit()
        db.close()

    async def clear_session(self, account_id: str, platform: str, session_key: str) -> None:
        db = get_db()
        row = db.execute(
            "SELECT id FROM sessions WHERE account_id=? AND platform=? AND session_key=? AND is_active=1",
            (account_id, platform, session_key)
        ).fetchone()
        if row:
            db.execute("DELETE FROM messages WHERE session_id=?", (row['id'],))
            db.execute("DELETE FROM sessions WHERE id=?", (row['id'],))
            db.commit()
        db.close()

    async def clear_all_sessions(self, account_id: str) -> None:
        db = get_db()
        rows = db.execute(
            "SELECT id FROM sessions WHERE account_id=?", (account_id,)
        ).fetchall()
        for row in rows:
            db.execute("DELETE FROM messages WHERE session_id=?", (row['id'],))
        db.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
        db.commit()
        db.close()

    async def cleanup_expired(self, ttl_minutes: int = 30) -> int:
        cutoff = (datetime.now() - timedelta(minutes=ttl_minutes)).isoformat()
        db = get_db()
        cursor = db.execute(
            "UPDATE sessions SET is_active=0 WHERE last_active_at < ? AND is_active=1",
            (cutoff,)
        )
        db.commit()
        count = cursor.rowcount
        db.close()
        return count

    async def get_session_info(self, account_id: str, platform: str, session_key: str) -> dict | None:
        """Get session stats for /status command"""
        db = get_db()
        row = db.execute(
            "SELECT s.last_active_at, COUNT(m.id) as msg_count "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "WHERE s.account_id=? AND s.platform=? AND s.session_key=? AND s.is_active=1",
            (account_id, platform, session_key)
        ).fetchone()
        db.close()
        if row:
            return {"rounds": row['msg_count'] // 2, "last_active": row['last_active_at'][:16]}
        return None

    async def get_account_active_sessions(self, account_id: str) -> list[dict]:
        db = get_db()
        rows = db.execute(
            "SELECT session_key, "
            "(SELECT COUNT(*) FROM messages WHERE session_id = s.id) AS msg_count "
            "FROM sessions s "
            "WHERE s.account_id=? AND s.is_active=1 "
            "AND s.last_active_at > datetime('now', '-30 minutes')",
            (account_id,)
        ).fetchall()
        db.close()
        return [{"key": r['session_key'], "rounds": r['msg_count'] // 2} for r in rows]
