import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from storage.database import get_db
from core.llm.client import LLMClient

router = APIRouter()


class ProviderCreate(BaseModel):
    name: str
    category: str = "chat"
    provider_type: str = "openai_compatible"
    model: str
    api_key: str
    base_url: str
    temperature: float = 0.8
    max_tokens: int = 512
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str = None
    category: str = None
    provider_type: str = None
    model: str = None
    api_key: str = None
    base_url: str = None
    temperature: float = None
    max_tokens: int = None
    is_default: bool = None


def _encrypt_api_key(api_key: str) -> str:
    from config import load_config
    config = load_config()
    if config.secret_key:
        from cryptography.fernet import Fernet
        key = config.secret_key.encode()
        if len(key) != 44:
            key = Fernet.generate_key()
        f = Fernet(key)
        return f.encrypt(api_key.encode()).decode()
    return api_key


def _decrypt_api_key(encrypted: str) -> str:
    from config import load_config
    config = load_config()
    if config.secret_key:
        try:
            from cryptography.fernet import Fernet
            key = config.secret_key.encode()
            if len(key) != 44:
                key = Fernet.generate_key()
            f = Fernet(key)
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            return encrypted
    return encrypted


def _row_to_provider(row: dict) -> dict:
    d = dict(row)
    d['is_default'] = bool(d['is_default'])
    d['temperature'] = float(d['temperature'])
    d['max_tokens'] = int(d['max_tokens'])
    return d


@router.get("")
async def list_providers():
    db = get_db()
    rows = db.execute("SELECT * FROM providers ORDER BY category, created_at").fetchall()
    db.close()
    return {"ok": True, "data": [_row_to_provider(dict(r)) for r in rows]}


@router.post("")
async def create_provider(body: ProviderCreate):
    pid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    # Strip whitespace from user input
    body.base_url = body.base_url.strip()
    body.model = body.model.strip()
    body.api_key = body.api_key.strip()
    api_key_enc = _encrypt_api_key(body.api_key)

    # If set as default, unset other defaults for same category
    db = get_db()
    if body.is_default:
        db.execute(
            "UPDATE providers SET is_default=0 WHERE category=?",
            (body.category,)
        )

    db.execute(
        "INSERT INTO providers (id, name, provider_type, category, model, "
        "api_key_enc, base_url, temperature, max_tokens, is_default, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, body.name, body.provider_type, body.category, body.model,
         api_key_enc, body.base_url, body.temperature, body.max_tokens,
         int(body.is_default), now, now)
    )
    db.commit()
    row = db.execute("SELECT * FROM providers WHERE id=?", (pid,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_provider(dict(row))}


@router.put("/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdate):
    db = get_db()
    row = db.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    updates = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None and v != "":  # skip None and empty string
            v = v.strip() if isinstance(v, str) else v  # strip whitespace
            if k == "api_key":
                updates["api_key_enc"] = _encrypt_api_key(v)
            elif k == "is_default":
                updates[k] = int(v)
                if v:
                    db.execute(
                        "UPDATE providers SET is_default=0 WHERE category=?",
                        (row['category'],)
                    )
            else:
                updates[k] = v

    if updates:
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(
            f"UPDATE providers SET {set_clause} WHERE id=?",
            (*updates.values(), provider_id)
        )
        db.commit()

    row = db.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_provider(dict(row))}


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str):
    db = get_db()
    # Check if any account references this provider
    refs = db.execute(
        "SELECT name FROM accounts WHERE chat_provider_id=? OR vision_provider_id=?",
        (provider_id, provider_id)
    ).fetchall()
    if refs:
        names = ", ".join(r['name'] for r in refs)
        db.close()
        return {"ok": False, "error": f"该模型被账户引用({names})，请先修改账户配置再删除"}
    db.execute("DELETE FROM providers WHERE id=?", (provider_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
    db.close()
    if not row:
        return {"ok": False, "error": "Not found"}

    from core.llm import ProviderConfig
    provider = ProviderConfig(
        id=row['id'], name=row['name'],
        provider_type=row['provider_type'], category=row['category'],
        model=row['model'], api_key=_decrypt_api_key(row['api_key_enc']),
        base_url=row['base_url'], temperature=row['temperature'],
        max_tokens=row['max_tokens'], is_default=bool(row['is_default'])
    )

    client = LLMClient()
    result = await client.test_connection(provider)
    return {"ok": True, "data": result}
