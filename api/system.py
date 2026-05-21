import time
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from storage.database import get_db

router = APIRouter()

_start_time = time.time()


# In-memory event queue for SSE subscribers
_sse_queues: list[asyncio.Queue] = []


def broadcast_event(event_type: str, data: dict):
    """Push event to all SSE subscribers"""
    payload = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    for q in _sse_queues:
        q.put_nowait(payload)


def get_broadcast():
    return broadcast_event


@router.get("/status")
async def system_status(request: Request):
    db = get_db()
    uptime_sec = int(time.time() - _start_time)
    hours = uptime_sec // 3600
    mins = (uptime_sec % 3600) // 60
    uptime_str = f"{hours}h {mins}m"

    # Today stats — all from DB (survives restart)
    try:
        received = db.execute(
            "SELECT COUNT(*) as c FROM messages WHERE role='user' AND created_at > datetime('now','-1 day')"
        ).fetchone()['c']
        sent = db.execute(
            "SELECT COUNT(*) as c FROM messages WHERE role='assistant' AND created_at > datetime('now','-1 day')"
        ).fetchone()['c']
        tokens = db.execute(
            "SELECT COALESCE(SUM(token_count), 0) as c FROM messages WHERE created_at > datetime('now','-1 day')"
        ).fetchone()['c']
        sessions = db.execute(
            "SELECT COUNT(*) as c FROM sessions WHERE is_active=1"
        ).fetchone()['c']
    except Exception:
        received, sent, tokens, sessions = 0, 0, 0, 0
    today = {
        "messages_received": received,
        "messages_sent": sent,
        "tokens_used": tokens,
        "active_sessions": sessions,
    }

    # Account statuses
    adapter_mgr = request.app.state.adapter_manager
    accounts = []
    try:
        rows = db.execute("SELECT * FROM accounts ORDER BY platform_id").fetchall()
        for r in rows:
            d = dict(r)
            adapter = adapter_mgr.get_adapter(d['id'])
            if adapter:
                st = adapter.status()
                status_str = 'connected' if st.get('connected') else 'connecting'
            else:
                status_str = 'running' if d.get('enabled') else 'stopped'
            accounts.append({"id": d['id'], "name": d['name'],
                             "platform": d['platform_id'], "status": status_str})
    except Exception:
        pass

    db.close()
    return {"ok": True, "data": {
        "uptime": uptime_str,
        "today": today,
        "accounts": accounts,
    }}


@router.get("/logs")
async def get_logs(level: str = None, limit: int = 100):
    import glob
    log_files = sorted(glob.glob("data/logs/anotherbot*.log"), reverse=True)
    lines = []
    for fpath in log_files[:3]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if level and level.upper() not in line:
                        continue
                    lines.append(line.strip())
        except FileNotFoundError:
            pass
    # Return the LAST (newest) lines
    return {"ok": True, "data": lines[-limit:]}


@router.get("/commands")
async def get_command_stats():
    db = get_db()
    rows = db.execute(
        "SELECT command, COUNT(*) as count FROM command_logs GROUP BY command ORDER BY count DESC"
    ).fetchall()
    db.close()
    return {"ok": True, "data": [{"command": r['command'], "count": r['count']} for r in rows]}


@router.get("/events/stream")
async def sse_stream():
    """Server-Sent Events for Dashboard live feed"""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues.append(queue)

    async def generate():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield data
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _sse_queues.remove(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
