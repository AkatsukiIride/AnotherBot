import uuid
import json
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from storage.database import get_db

router = APIRouter()


class AccountCreate(BaseModel):
    platform_id: str
    name: str
    config_json: dict = {}
    persona_id: str = None
    chat_provider_id: str = None
    vision_provider_id: str = None


class AccountUpdate(BaseModel):
    name: str = None
    config_json: dict = None
    persona_id: str = None
    chat_provider_id: str = None
    vision_provider_id: str = None


def _row_to_account(row: dict) -> dict:
    d = dict(row)
    d['enabled'] = bool(d['enabled'])
    d['config_json'] = json.loads(d.get('config_json', '{}'))
    d['favorite_sticker_codes'] = json.loads(d.get('favorite_sticker_codes', '[]'))
    return d


async def _add_status(account: dict, adapter_manager) -> dict:
    adapter = adapter_manager.get_adapter(account['id'])
    if adapter:
        st = adapter.status()
        if st.get('error'):
            account['status'] = 'error'
        elif st.get('connected'):
            account['status'] = 'connected'
        else:
            account['status'] = 'connecting'
    else:
        account['status'] = 'running' if account['enabled'] else 'stopped'
    return account


def _get_adapter_manager(request: Request):
    return request.app.state.adapter_manager


def _get_context_manager(request: Request):
    return request.app.state.context_manager


@router.get("")
async def list_accounts(request: Request):
    adapter_mgr = _get_adapter_manager(request)
    ctx_mgr = _get_context_manager(request)
    db = get_db()
    rows = db.execute("SELECT * FROM accounts ORDER BY platform_id, created_at").fetchall()
    db.close()
    result = []
    for r in rows:
        acc = _row_to_account(dict(r))
        acc = await _add_status(acc, adapter_mgr)
        acc['active_sessions'] = await ctx_mgr.get_account_active_sessions(r['id'])
        result.append(acc)
    return {"ok": True, "data": result}


@router.post("")
async def create_account(body: AccountCreate, request: Request):
    # Validate platform exists
    db = get_db()
    platform = db.execute("SELECT * FROM platforms WHERE id=?", (body.platform_id,)).fetchone()
    if not platform:
        db.close()
        return {"ok": False, "error": f"Unknown platform: {body.platform_id}"}

    # Check duplicate: same platform + same bot_qq
    bot_qq = body.config_json.get('bot_qq', '')
    if bot_qq:
        existing = db.execute(
            "SELECT id, name FROM accounts WHERE platform_id=? AND config_json LIKE ?",
            (body.platform_id, f'%\"bot_qq\": \"{bot_qq}\"%')
        ).fetchone()
        if existing:
            db.close()
            return {"ok": False, "error": f"QQ号 {bot_qq} 已被账户「{existing['name']}」使用"}

    aid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    config_json = json.dumps(body.config_json, ensure_ascii=False)
    db.execute(
        "INSERT INTO accounts (id, platform_id, name, config_json, persona_id, "
        "chat_provider_id, vision_provider_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, body.platform_id, body.name, config_json, body.persona_id,
         body.chat_provider_id, body.vision_provider_id, now, now)
    )
    db.commit()
    row = db.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    db.close()

    acc = _row_to_account(dict(row))
    adapter_mgr = _get_adapter_manager(request)
    return {"ok": True, "data": await _add_status(acc, adapter_mgr)}


@router.get("/{account_id}")
async def get_account(account_id: str, request: Request):
    db = get_db()
    row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    db.close()
    if not row:
        return {"ok": False, "error": "Not found"}

    acc = _row_to_account(dict(row))
    adapter_mgr = _get_adapter_manager(request)
    ctx_mgr = _get_context_manager(request)
    acc = await _add_status(acc, adapter_mgr)
    acc['active_sessions'] = await ctx_mgr.get_account_active_sessions(account_id)
    return {"ok": True, "data": acc}


@router.put("/{account_id}")
async def update_account(account_id: str, body: AccountUpdate):
    db = get_db()
    row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    updates = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            updates[k] = json.dumps(v, ensure_ascii=False) if k == "config_json" else v

    if updates:
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(
            f"UPDATE accounts SET {set_clause} WHERE id=?",
            (*updates.values(), account_id)
        )
        db.commit()

    row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_account(dict(row))}


@router.delete("/{account_id}")
async def delete_account(account_id: str, request: Request):
    adapter_mgr = _get_adapter_manager(request)
    # Stop adapter first if running
    if adapter_mgr.get_adapter(account_id):
        await adapter_mgr.stop_account(account_id)

    db = get_db()
    db.execute("UPDATE accounts SET enabled=0 WHERE id=?", (account_id,))
    db.execute("DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE account_id=?)", (account_id,))
    db.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
    db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/{account_id}/enable")
async def enable_account(account_id: str, request: Request):
    adapter_mgr = _get_adapter_manager(request)
    db = get_db()
    row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    try:
        await adapter_mgr.start_account(dict(row))
        db.execute("UPDATE accounts SET enabled=1 WHERE id=?", (account_id,))
        db.commit()
        db.close()
        status = adapter_mgr.get_adapter(account_id).status() if adapter_mgr.get_adapter(account_id) else {}
        return {"ok": True, "data": {"status": "connected" if status.get('connected') else "waiting"}}
    except Exception as e:
        db.close()
        return {"ok": False, "error": str(e)}


@router.post("/{account_id}/disable")
async def disable_account(account_id: str, request: Request):
    adapter_mgr = _get_adapter_manager(request)
    await adapter_mgr.stop_account(account_id)
    db = get_db()
    db.execute("UPDATE accounts SET enabled=0 WHERE id=?", (account_id,))
    db.commit()
    db.close()
    return {"ok": True, "data": {"status": "stopped"}}


@router.post("/{account_id}/reconnect")
async def reconnect_account(account_id: str, request: Request):
    adapter_mgr = _get_adapter_manager(request)
    try:
        await adapter_mgr.restart_account(account_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/{account_id}/clear-context")
async def clear_account_context(account_id: str, request: Request):
    ctx_mgr = _get_context_manager(request)
    await ctx_mgr.clear_all_sessions(account_id)
    return {"ok": True}
