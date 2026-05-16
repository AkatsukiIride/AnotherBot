import uuid
from datetime import datetime

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from storage.database import get_db

router = APIRouter()


class PersonaCreate(BaseModel):
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_message: str = ""
    example_dialogue: str = ""
    custom_prompt: str = ""
    post_instructions: str = ""
    avatar_path: str = ""
    author: str = ""


class PersonaUpdate(BaseModel):
    name: str = None
    description: str = None
    personality: str = None
    scenario: str = None
    first_message: str = None
    example_dialogue: str = None
    custom_prompt: str = None
    post_instructions: str = None
    avatar_path: str = None
    author: str = None


def _row_to_persona(row: dict) -> dict:
    d = dict(row)
    d['is_active'] = bool(d['is_active'])
    return d


@router.get("")
async def list_personas():
    db = get_db()
    rows = db.execute("SELECT * FROM personas ORDER BY created_at DESC").fetchall()
    db.close()
    return {"ok": True, "data": [_row_to_persona(dict(r)) for r in rows]}


@router.post("")
async def create_persona(body: PersonaCreate):
    pid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO personas (id, name, description, personality, scenario, "
        "first_message, example_dialogue, custom_prompt, post_instructions, "
        "avatar_path, author, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, body.name, body.description, body.personality, body.scenario,
         body.first_message, body.example_dialogue, body.custom_prompt,
         body.post_instructions, body.avatar_path, body.author, now, now)
    )
    db.commit()
    row = db.execute("SELECT * FROM personas WHERE id=?", (pid,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_persona(dict(row))}


@router.get("/{persona_id}")
async def get_persona(persona_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    db.close()
    if not row:
        return {"ok": False, "error": "Not found"}
    return {"ok": True, "data": _row_to_persona(dict(row))}


@router.put("/{persona_id}")
async def update_persona(persona_id: str, body: PersonaUpdate):
    db = get_db()
    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    updates = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            updates[k] = v

    if updates:
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(
            f"UPDATE personas SET {set_clause} WHERE id=?",
            (*updates.values(), persona_id)
        )
        db.commit()

    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_persona(dict(row))}


@router.delete("/{persona_id}")
async def delete_persona(persona_id: str):
    db = get_db()
    refs = db.execute(
        "SELECT name FROM accounts WHERE persona_id=?",
        (persona_id,)
    ).fetchall()
    if refs:
        names = ", ".join(r['name'] for r in refs)
        db.close()
        return {"ok": False, "error": f"该人设被账户引用({names})，请先修改账户配置再删除"}
    db.execute("DELETE FROM personas WHERE id=?", (persona_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/{persona_id}/activate")
async def activate_persona(persona_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}
    # Toggle: if already active, deactivate; otherwise set as active
    if row['is_active']:
        db.execute("UPDATE personas SET is_active=0 WHERE id=?", (persona_id,))
    else:
        db.execute("UPDATE personas SET is_active=0")
        db.execute("UPDATE personas SET is_active=1 WHERE id=?", (persona_id,))
    db.commit()
    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_persona(dict(row))}


@router.post("/import")
async def import_persona(file: UploadFile = File(...)):
    """Import SillyTavern character card PNG"""
    try:
        png_bytes = await file.read()
        # Parse PNG tEXt chunk for base64 JSON (spec_v2)
        import struct
        import zlib
        import json

        # Simple PNG chunk parser for tEXt "chara"
        pos = 8  # skip PNG signature
        result = {}
        while pos < len(png_bytes):
            length = struct.unpack(">I", png_bytes[pos:pos+4])[0]
            pos += 4
            chunk_type = png_bytes[pos:pos+4].decode('ascii')
            pos += 4
            chunk_data = png_bytes[pos:pos+length]
            pos += length + 4  # skip CRC
            if chunk_type == "tEXt":
                raw = chunk_data.decode('latin-1')
                keyword, _, text = raw.partition('\x00')
                if keyword.lower() in ("chara", "ccv3"):
                    try:
                        decoded = zlib.decompress(
                            text.encode('latin-1')
                        ).decode('utf-8')
                    except Exception:
                        import base64
                        decoded = base64.b64decode(text).decode('utf-8')
                    result = json.loads(decoded)
                    break

        if not result:
            return {"ok": False, "error": "未能从图片中解析角色卡数据"}

        card = result.get("data", result)
        persona_data = PersonaCreate(
            name=card.get("name", "未命名"),
            description=card.get("description", ""),
            personality=card.get("personality", ""),
            scenario=card.get("scenario", ""),
            first_message=card.get("first_mes", ""),
            example_dialogue=card.get("mes_example", ""),
            custom_prompt=card.get("system_prompt", ""),
            post_instructions=card.get("post_history_instructions", ""),
            author=card.get("creator", ""),
        )
        return await create_persona(persona_data)
    except Exception as e:
        return {"ok": False, "error": f"导入失败: {str(e)}"}
