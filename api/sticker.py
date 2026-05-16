import uuid
import os
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse
from storage.database import get_db
from config import load_config
from PIL import Image

router = APIRouter()
_config = load_config()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB
STICKER_MAX_PX = 180       # Comfortable chat sticker size
STICKER_MAX_KB = 120       # Reasonable for 180x180 PNG


def _compress_sticker(img_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Resize and compress sticker. GIFs are kept as-is."""
    # Don't touch GIFs — preserve animation
    if 'gif' in mime_type:
        return img_bytes, mime_type

    img = Image.open(BytesIO(img_bytes))
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGBA')
    w, h = img.size
    if w > STICKER_MAX_PX or h > STICKER_MAX_PX:
        ratio = STICKER_MAX_PX / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='PNG', optimize=True)
    result = buf.getvalue()
    if len(result) > STICKER_MAX_KB * 1024:
        ratio2 = 0.6
        img = img.resize((int(img.width * ratio2), int(img.height * ratio2)), Image.LANCZOS)
        buf2 = BytesIO()
        img.save(buf2, format='PNG', optimize=True)
        result = buf2.getvalue()
    return result, 'image/png'


def _generate_code(existing_codes: set, limit: int) -> str | None:
    used = {int(c[2:]) for c in existing_codes if c.startswith("EM")}
    for i in range(1, limit + 1):
        if i not in used:
            return f"EM{i:04d}"
    return None


def _row_to_sticker(row: dict) -> dict:
    d = dict(row)
    d['file_size'] = int(d['file_size'])
    return d


@router.get("/image/{code}")
async def get_sticker_image(code: str):
    """Serve sticker image file"""
    db = get_db()
    row = db.execute("SELECT file_path, mime_type FROM stickers WHERE code=?", (code,)).fetchone()
    db.close()
    if not row or not os.path.exists(row['file_path']):
        return {"ok": False, "error": "Not found"}
    return FileResponse(row['file_path'], media_type=row['mime_type'])


@router.get("")
async def list_stickers(search: str = "", sort: str = "latest"):
    db = get_db()
    order = "uploaded_at DESC" if sort == "latest" else "uploaded_at ASC"
    if search:
        rows = db.execute(
            f"SELECT * FROM stickers WHERE description LIKE ? OR filename LIKE ? OR code LIKE ? ORDER BY {order}",
            (f"%{search}%", f"%{search}%", f"%{search}%")
        ).fetchall()
    else:
        rows = db.execute(f"SELECT * FROM stickers ORDER BY {order}").fetchall()
    db.close()
    return {"ok": True, "data": [_row_to_sticker(dict(r)) for r in rows]}


@router.post("")
async def upload_sticker(file: UploadFile = File(...),
                         auto_describe: bool = Form(False)):
    if file.content_type not in ALLOWED_TYPES:
        return {"ok": False, "error": "不支持的文件格式，仅支持 JPG/PNG/GIF/WebP"}

    raw = await file.read()
    if len(raw) > MAX_SIZE:
        return {"ok": False, "error": "文件过大，限制 10MB"}

    # Compress sticker (GIFs preserved as-is)
    content, mime_type = _compress_sticker(raw, file.content_type)

    # Check limit
    db = get_db()
    count = db.execute("SELECT COUNT(*) as c FROM stickers").fetchone()['c']
    if count >= _config.sticker_limit:
        db.close()
        return {"ok": False, "error": f"表情包已达上限({_config.sticker_limit}张)，请先删除旧表情包"}

    # Generate code
    existing = {r['code'] for r in db.execute("SELECT code FROM stickers").fetchall()}
    code = _generate_code(existing, _config.sticker_limit)
    if not code:
        db.close()
        return {"ok": False, "error": "无法分配编号"}

    # Save file, preserving GIF extension
    ext = ".gif" if 'gif' in mime_type else ".png"
    filename = f"{code}{ext}"
    sticker_dir = os.path.join(_config.data_dir, "stickers")
    os.makedirs(sticker_dir, exist_ok=True)
    file_path = os.path.join(sticker_dir, filename)
    with open(file_path, "wb") as f:
        f.write(content)

    sid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO stickers (id, code, filename, file_path, description, file_size, mime_type, uploaded_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (sid, code, filename, file_path, "", len(content), mime_type, now)
    )
    db.commit()
    row = db.execute("SELECT * FROM stickers WHERE id=?", (sid,)).fetchone()
    db.close()

    result = _row_to_sticker(dict(row))

    # Auto-describe via vision model
    if auto_describe:
        description = await _describe_sticker(file_path, file.content_type, db)
        if description:
            db2 = get_db()
            db2.execute("UPDATE stickers SET description=? WHERE id=?", (description, sid))
            db2.commit()
            db2.close()
            result['description'] = description

    db.close()
    return {"ok": True, "data": result}


async def _describe_sticker(file_path: str, mime_type: str, db) -> str | None:
    """Call vision model to describe a sticker image"""
    import base64
    from core.llm.client import LLMClient
    from core.llm import ProviderConfig

    # Load vision provider
    row = db.execute(
        "SELECT * FROM providers WHERE category='vision' AND is_default=1 LIMIT 1"
    ).fetchone()
    if not row:
        return None

    p = dict(row)
    from api.provider import _decrypt_api_key
    provider = ProviderConfig(
        id=p['id'], name=p['name'], model=p['model'],
        api_key=_decrypt_api_key(p['api_key_enc']),
        base_url=p['base_url'], temperature=0.7, max_tokens=100,
        is_default=bool(p['is_default']),
    )

    # Read and encode image
    with open(file_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()

    prompt = "请用50字以内描述这张表情包图片：画面核心内容是什么，传达了什么信息或情绪，适合在什么对话场景使用。直接输出描述文本。"
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}},
            {"type": "text", "text": prompt},
        ]
    }]

    try:
        client = LLMClient()
        result = await client.chat(messages, provider)
        return result.strip()[:100]  # Cap at 100 chars
    except Exception:
        return None


@router.put("/{sticker_id}")
async def update_sticker(sticker_id: str, body: dict):
    db = get_db()
    row = db.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    if 'description' in body:
        db.execute("UPDATE stickers SET description=? WHERE id=?", (body['description'], sticker_id))
        db.commit()

    row = db.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    db.close()
    return {"ok": True, "data": _row_to_sticker(dict(row))}


@router.post("/{sticker_id}/re-describe")
async def re_describe_sticker(sticker_id: str):
    """Re-run vision model on an existing sticker"""
    db = get_db()
    row = db.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    r = dict(row)
    if not os.path.exists(r['file_path']):
        db.close()
        return {"ok": False, "error": "文件不存在"}

    description = await _describe_sticker(r['file_path'], r['mime_type'], db)
    if description:
        db.execute("UPDATE stickers SET description=? WHERE id=?", (description, sticker_id))
        db.commit()
        r['description'] = description

    db.close()
    return {"ok": True, "data": _row_to_sticker(r)}


@router.delete("/{sticker_id}")
async def delete_sticker(sticker_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if not row:
        db.close()
        return {"ok": False, "error": "Not found"}

    r = dict(row)
    # Check if any account has this in favorites
    accounts = db.execute("SELECT name FROM accounts WHERE favorite_sticker_codes LIKE ?",
                          (f'%"{r["code"]}"%',)).fetchall()
    if accounts:
        names = ", ".join(a['name'] for a in accounts)
        db.close()
        return {"ok": False,
                "error": f"该表情被以下账户收藏: {names}，请先取消收藏后再删除"}

    # Delete file
    if os.path.exists(r['file_path']):
        os.remove(r['file_path'])

    db.execute("DELETE FROM stickers WHERE id=?", (sticker_id,))
    db.commit()
    db.close()
    return {"ok": True}
