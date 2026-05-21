import os
import re
import random
from abc import ABC, abstractmethod

from models.message import (
    AstrMessageEvent, MessageComponent, MessageComponentType,
)


def _resolve_stickers(text: str) -> list[MessageComponent]:
    """Split text by EMxxxx codes and resolve valid stickers to IMAGE components."""
    pattern = r'(?:\[)?(EM\d{4})(?:\])?'
    parts = re.split(pattern, text)
    chain = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # Odd = potential sticker code EMxxxx
            code = part
            from storage.database import get_db
            db = get_db()
            row = db.execute("SELECT file_path FROM stickers WHERE code=?", (code,)).fetchone()
            db.close()
            if row and os.path.exists(row['file_path']):
                chain.append(MessageComponent(
                    type=MessageComponentType.IMAGE,
                    data={"file": os.path.abspath(row['file_path'])}
                ))
                continue
            chain.append(MessageComponent(type=MessageComponentType.TEXT, data={"text": part}))
        elif part.strip():
            chain.append(MessageComponent(type=MessageComponentType.TEXT, data={"text": part}))
    return chain if chain else [MessageComponent(type=MessageComponentType.TEXT, data={"text": text})]


async def _roleplay_reply(event: AstrMessageEvent, data_text: str, role_prompt: str,
                          llm_client=None, persona_engine=None, max_tokens: int = 300) -> list[MessageComponent]:
    """Wrap raw data in persona-styled reply. Returns message chain with stickers resolved."""
    if not llm_client or not persona_engine:
        return [MessageComponent(type=MessageComponentType.TEXT, data={"text": data_text})]
    from storage.database import get_db
    from core.persona import Persona
    db = get_db()
    acc = db.execute("SELECT persona_id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
    p_row = None
    if acc and acc['persona_id']:
        p_row = db.execute("SELECT * FROM personas WHERE id=?", (acc['persona_id'],)).fetchone()
    if not p_row:
        p_row = db.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
    db.close()
    if not p_row:
        return [MessageComponent(type=MessageComponentType.TEXT, data={"text": data_text})]
    persona = Persona(**dict(p_row))
    system = persona_engine.build_system_prompt(persona).replace("<!-- STICKERS -->", "")
    try:
        provider = _get_chat_provider(max_tokens)
        if not provider:
            return [MessageComponent(type=MessageComponentType.TEXT, data={"text": data_text})]
        reply = await llm_client.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"{role_prompt}\n\n"
                f"---原始数据（必须逐条完整保留，不得删改遗漏）---\n"
                f"{data_text}\n"
                f"---结束---"
            )}
        ], provider)
        text = reply.strip() or data_text
        return _resolve_stickers(text)
    except Exception:
        return [MessageComponent(type=MessageComponentType.TEXT, data={"text": data_text})]


def _get_chat_provider(max_tokens: int = 512):
    from storage.database import get_db
    from core.llm import ProviderConfig
    db = get_db()
    row = db.execute("SELECT * FROM providers WHERE category='chat' AND is_default=1 LIMIT 1").fetchone()
    db.close()
    if not row: return None
    p = dict(row)
    from api.provider import _decrypt_api_key
    return ProviderConfig(id=p['id'], name=p['name'], model=p['model'],
                          api_key=_decrypt_api_key(p['api_key_enc']),
                          base_url=p['base_url'], temperature=0.8, max_tokens=max_tokens)


class Command(ABC):
    @abstractmethod
    async def execute(self, event: AstrMessageEvent, args: str) -> str:
        ...


class ResetCommand(Command):
    def __init__(self, context_manager):
        self.ctx = context_manager

    async def execute(self, event, args):
        await self.ctx.clear_session(
            event.account_id, event.platform,
            event.message.session_id
        )
        return "✅ 上下文已清空，下次@我开启新话题吧"


class NewSessionCommand(Command):
    def __init__(self, context_manager):
        self.ctx = context_manager

    async def execute(self, event, args):
        await self.ctx.end_session(
            event.account_id, event.platform,
            event.message.session_id
        )
        return "✅ 当前对话已结束，下次@我开启新话题"


class StatusCommand(Command):
    def __init__(self, context_manager):
        self.ctx = context_manager

    async def execute(self, event, args):
        info = await self.ctx.get_session_info(
            event.account_id, event.platform,
            event.message.session_id
        )
        if info:
            return (
                f"\U0001f4ca 当前会话: {info['rounds']}轮对话 | "
                f"最近活跃: {info['last_active']} | "
                f"指令: /reset /new /status /help"
            )
        return "\U0001f4ca 暂无活跃会话 | 指令: /reset /new /status /help"


class SearchCommand(Command):
    def __init__(self, llm_client, persona_engine, context_manager):
        self.llm = llm_client
        self.persona = persona_engine
        self.ctx = context_manager

    async def execute(self, event, args):
        if not args.strip():
            return "请在 /search 后面加上搜索关键词，如 /search 今天天气"
        from core.search import search_and_rank, format_results_for_llm
        from datetime import datetime

        today = datetime.now()
        today_str = today.strftime("%Y年%m月%d日")

        # Full pipeline: search → dedup → score → fetch
        result = await search_and_rank(args.strip(), max_results=5, fetch_pages=2, reference_date=today)
        if not result['results']:
            return "唔...没搜到相关内容，换个关键词试试？"

        context = format_results_for_llm(result['results'], result['pages'], reference_date=today)

        # Build persona — check account binding first, fall back to system active
        from storage.database import get_db
        from core.persona import Persona
        db = get_db()
        # Check account-bound persona
        acc_row = db.execute("SELECT persona_id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
        p_row = None
        if acc_row and acc_row['persona_id']:
            p_row = db.execute("SELECT * FROM personas WHERE id=?", (acc_row['persona_id'],)).fetchone()
        if not p_row:
            p_row = db.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
        db.close()
        persona = Persona(**dict(p_row)) if p_row else Persona(id="default", name="助手", description="AI助手")
        system = self.persona.build_system_prompt(persona)
        system = system.replace("<!-- STICKERS -->", "")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"今天是{today_str}，请严格以这个日期为基准。\n\n"
                f"用户搜索: {args.strip()}\n\n"
                f"搜索结果（按相关度和时效性排序，含日期标注）:\n"
                f"{context}\n\n"
                f"请用你角色的语气回答，但信息必须来自以上搜索结果。不要编造。注意：\n"
                f"1. 对比搜索结果日期和今天({today_str})，判断时效。事件已发生就不要描述为'即将'\n"
                f"2. 如果信息来自较早日期，告知用户'据N月份报道...'\n"
                f"3. 不要编排格式，不要输出JSON或代码，不要用Markdown图片格式\n"
            f"4. 可以用颜文字(｡･ω･｡)表达情绪，但不要用图片链接"
            )},
        ]
        try:
            reply = await self.llm.chat(messages, self._get_chat_provider())
            import re
            reply = re.sub(r'\{[^}]*sticker[^}]*\}', '', reply)
            reply = re.sub(r'\[sticker[^\]]*\]', '', reply)
            reply = re.sub(r'!\[.*?\]\(https?://[^\s)]+\)', '', reply)
            return reply.strip()
        except Exception:
            return "唔...搜索出错了，待会再试试？"

    def _get_chat_provider(self):
        from storage.database import get_db
        from core.llm import ProviderConfig
        db = get_db()
        row = db.execute("SELECT * FROM providers WHERE category='chat' AND is_default=1 LIMIT 1").fetchone()
        db.close()
        if not row:
            return None
        p = dict(row)
        from api.provider import _decrypt_api_key
        return ProviderConfig(
            id=p['id'], name=p['name'], model=p['model'],
            api_key=_decrypt_api_key(p['api_key_enc']),
            base_url=p['base_url'], temperature=0.7, max_tokens=512,
        )


class HelpCommand(Command):
    def __init__(self, registry_ref):
        self._registry = registry_ref  # weak ref to parser's registry

    async def execute(self, event, args):
        platform = event.platform
        lines = ["\U0001f4cb 可用指令:"]
        for name, (handler, platforms) in self._registry.items():
            if platforms is None or platform in platforms:
                lines.append(f"  {name}")
        return "\n".join(lines)


class VisionCommand(Command):
    """手动识图: /vision + 图片 → 识图→走人设回复"""
    def __init__(self, llm_client, persona_engine):
        self.llm = llm_client
        self.persona = persona_engine

    async def execute(self, event, args):
        if not getattr(event.message, 'image_url', None):
            return "请发一张图片，然后加上 /vision 指令哦～"
        import httpx
        from storage.database import get_db
        from core.persona import Persona

        # Step 1: vision API → describe
        db = get_db()
        row = db.execute(
            "SELECT * FROM providers WHERE category='vision' AND is_default=1 LIMIT 1"
        ).fetchone()
        if not row:
            db.close()
            return "⚠️ 未配置识图模型"
        p = dict(row)
        from api.provider import _decrypt_api_key
        api_key = _decrypt_api_key(p['api_key_enc'])
        body = {
            "model": p['model'],
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": event.message.image_url}},
                {"type": "text", "text": "详细描述这张图片，包括人物、场景、动作、表情。100字以内。"},
            ]}],
            "max_tokens": 200, "temperature": 0.5,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{p['base_url']}/chat/completions", json=body, headers=headers)
                data = resp.json()
                if resp.status_code != 200:
                    db.close()
                    return f"识图API错误({resp.status_code}): {data.get('message',str(data)[:100])}"
                desc = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            db.close()
            return f"识图出错了: {e}"
        db.close()

        # Step 2: get persona → chat API → reply in character
        db2 = get_db()
        acc = db2.execute("SELECT persona_id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
        p_row = None
        if acc and acc['persona_id']:
            p_row = db2.execute("SELECT * FROM personas WHERE id=?", (acc['persona_id'],)).fetchone()
        if not p_row:
            p_row = db2.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
        db2.close()
        persona = Persona(**dict(p_row)) if p_row else Persona(id="default", name="助手")
        system = self.persona.build_system_prompt(persona)
        system = system.replace("<!-- STICKERS -->", "")

        msg = [{"role": "system", "content": system},
               {"role": "user", "content": f"有人给你看了一张图：{desc}。用你的角色语气点评这张图，说说图中最吸引你的细节。要有画面感，像真人聊天一样自然，3-5句。"}]
        try:
            provider = self._get_chat_provider()
            if provider:
                return await self.llm.chat(msg, provider)
            return desc
        except Exception:
            return desc

    def _get_chat_provider(self):
        from storage.database import get_db
        from core.llm import ProviderConfig
        db = get_db()
        row = db.execute("SELECT * FROM providers WHERE category='chat' AND is_default=1 LIMIT 1").fetchone()
        db.close()
        if not row: return None
        p = dict(row)
        from api.provider import _decrypt_api_key
        return ProviderConfig(id=p['id'], name=p['name'], model=p['model'],
                              api_key=_decrypt_api_key(p['api_key_enc']),
                              base_url=p['base_url'], temperature=0.7, max_tokens=512)


async def _roleplay_commentary(event: AstrMessageEvent, data_text: str, list_label: str,
                                llm_client=None, persona_engine=None, max_tokens: int = 500) -> tuple[str, str]:
    """LLM outputs opener + selected commentary only (no data transcription).
    Returns (opener: str, commentary: str). Caller stitches raw data in between."""
    if not llm_client or not persona_engine:
        return "", ""
    from storage.database import get_db
    from core.persona import Persona
    db = get_db()
    acc = db.execute("SELECT persona_id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
    p_row = None
    if acc and acc['persona_id']:
        p_row = db.execute("SELECT * FROM personas WHERE id=?", (acc['persona_id'],)).fetchone()
    if not p_row:
        p_row = db.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
    db.close()
    if not p_row:
        return "", ""
    persona = Persona(**dict(p_row))
    system = persona_engine.build_system_prompt(persona).replace("<!-- STICKERS -->", "")
    try:
        provider = _get_chat_provider(max_tokens)
        if not provider:
            return "", ""
        prompt = (
            f"以下是{list_label}。先写一句生动简短的开场白（体现你的角色语气，1-3句话），"
            f"然后浏览列表挑选1-3条你最感兴趣的，用角色语气自然点评，"
            f"融入一段话中，提及《标题》即可。不要用'对第X条'这类公式化表述，"
            f"不要逐条列点评清单。\n\n"
            f"---数据列表（供浏览，不要复制输出）---\n"
            f"{data_text}\n"
            f"---\n\n"
            f"回复格式（'---' 单独一行作为分隔）：\n"
            f"[开场白]\n\n"
            f"---\n"
            f"[自然段落的点评，提及《标题》]"
        )
        reply = await llm_client.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ], provider)
        text = reply.strip()
        if not text:
            return "", ""
        # Try new delimiter first, then old one for compat
        for delim in ("\n---\n", "\n---点评---\n", "---点评---"):
            if delim in text:
                parts = text.split(delim, 1)
                opener = parts[0].strip()
                commentary = parts[1].strip() if len(parts) > 1 else ""
                return opener, commentary
        # Fallback: entire response is opener
        return text, ""
    except Exception:
        return "", ""


class BilibiliHotCommand(Command):
    """B站实时热搜"""
    def __init__(self, llm, persona): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8, headers={'User-Agent': 'Mozilla/5.0'}) as c:
                r = await c.get('https://s.search.bilibili.com/main/hotword?limit=10')
                items = r.json().get('list', [])[:10]
                if not items: return "暂无热搜"

            # Build data for LLM browsing
            data_for_llm = "\n".join(f"{i+1}. {it.get('show_name','')}" for i, it in enumerate(items))

            # Build display data (guaranteed accurate, not LLM-touched)
            data_display = "\n".join(f"{i+1}. {it.get('show_name','')}" for i, it in enumerate(items))

            opener, commentary = await _roleplay_commentary(
                event, data_for_llm, "B站实时热搜榜", self.llm, self.persona, 500)

            parts = [opener] if opener else []
            parts.append(data_display)
            if commentary:
                parts.append(commentary)
            return _resolve_stickers("\n\n".join(parts))
        except Exception:
            return "获取失败"


class BilibiliTrendingCommand(Command):
    """B站热门视频"""
    def __init__(self, llm, persona): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        try:
            from bilibili_api import hot
            data = await hot.get_hot_videos()
            items = data.get('list', [])[:10]
            if not items:
                return "暂无热门视频"

            # Build data for LLM browsing (compact)
            data_for_llm_lines = []
            # Build display data (full info, guaranteed accurate)
            data_display_lines = []
            for i, v in enumerate(items, 1):
                title = v.get('title','')
                author = v.get('owner',{}).get('name','')
                bvid = v.get('bvid','')
                link = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                play = v.get('stat',{}).get('view',0)//10000
                data_for_llm_lines.append(f"{i}. {title} (UP:{author})")
                data_display_lines.append(f"{i}. {title}\n   UP:{author} | {play}万播放 | {link}")

            opener, commentary = await _roleplay_commentary(
                event, "\n".join(data_for_llm_lines), "B站热门视频榜",
                self.llm, self.persona, 700)

            parts = [opener] if opener else []
            parts.append("\n".join(data_display_lines))
            if commentary:
                parts.append(commentary)
            return _resolve_stickers("\n\n".join(parts))
        except Exception:
            return "获取失败，待会再试？"


class BilibiliRecommendCommand(Command):
    """B站视频推荐"""
    def __init__(self, llm_client, persona_engine):
        self.llm = llm_client
        self.persona = persona_engine

    async def execute(self, event, args):
        try:
            import random
            from bilibili_api import hot
            data = await hot.get_hot_videos()
            items = data.get('list', [])[:30]
            if not items:
                return "暂无热门视频"

            pool = [v for v in items if v.get('desc') or v.get('rcmd_reason')]
            if not pool:
                pool = items
            v = random.choice(pool)

            title = v.get('title', '')
            bvid = v.get('bvid', '')
            desc = v.get('desc', '')[:200] if v.get('desc') else ''
            rcmd = v.get('rcmd_reason', {}).get('content', '') if isinstance(v.get('rcmd_reason'), dict) else ''
            stat = v.get('stat', {})
            play = stat.get('view', 0)
            play_str = f"{play//10000}万播放" if play >= 10000 else f"{play}播放"
            danmu = stat.get('danmaku', 0)
            author = v.get('owner', {}).get('name', '')
            link = f"https://www.bilibili.com/video/{bvid}" if bvid else ""

            # Data for LLM to browse
            data_for_llm = (f"1. {title} (UP:{author}, {play_str})\n"
                          f"   简介: {desc or '无'}"
                          + (f"\n   推荐理由: {rcmd}" if rcmd else ""))

            # Display data (program-generated, guaranteed complete)
            data_display = (f"《{title}》\n"
                          f"UP主: {author} | {play_str} | {danmu}弹幕\n"
                          f"链接: {link}\n"
                          f"简介: {desc or '无'}"
                          + (f"\n推荐理由: {rcmd}" if rcmd else ""))

            opener, commentary = await _roleplay_commentary(
                event, data_for_llm, "B站视频推荐", self.llm, self.persona, 400)

            parts = [opener] if opener else []
            parts.append(data_display)
            if commentary:
                parts.append(commentary)
            return _resolve_stickers("\n\n".join(parts))
        except Exception:
            return "获取失败，待会再试？"

def _get_persona_key(event: AstrMessageEvent) -> str:
    """Get persona key for scoping memories across sessions"""
    from storage.database import get_db
    db = get_db()
    # Check account-bound persona first
    acc = db.execute("SELECT persona_id FROM accounts WHERE id=?", (event.account_id,)).fetchone()
    pid = dict(acc)['persona_id'] if acc else None
    if not pid:
        row = db.execute("SELECT id FROM personas WHERE is_active=1 LIMIT 1").fetchone()
        pid = row['id'] if row else 'default'
    db.close()
    return f"persona:{pid}"


class RememberCommand(Command):
    """记忆设置: /remember key value → 绑定人设存储"""
    async def execute(self, event, args):
        parts = args.split(None, 1)
        if len(parts) < 2:
            return "用法: /remember 关键词 内容"
        key, value = parts[0], parts[1]
        from storage.database import get_db
        import uuid
        db = get_db()
        sk = _get_persona_key(event)
        sid = str(uuid.uuid4())
        db.execute(
            "INSERT OR REPLACE INTO user_memories (id, session_key, mem_key, mem_value) VALUES (?,?,?,?)",
            (sid, sk, key, value)
        )
        db.commit()
        db.close()
        return f"✅ 记住了: {key} = {value}"


class ForgetCommand(Command):
    """记忆删除: /forget key"""
    async def execute(self, event, args):
        key = args.strip()
        if not key:
            return "用法: /forget 关键词"
        from storage.database import get_db
        db = get_db()
        sk = _get_persona_key(event)
        db.execute("DELETE FROM user_memories WHERE session_key=? AND mem_key=?", (sk, key))
        db.commit()
        db.close()
        return f"✅ 已删除: {key}"


class ListMemoryCommand(Command):
    """记忆列表: /list-memory → 编号列表，/forget 编号 删除"""
    async def execute(self, event, args):
        from storage.database import get_db
        db = get_db()
        sk = _get_persona_key(event)
        rows = db.execute(
            "SELECT mem_key, mem_value FROM user_memories WHERE session_key=?", (sk,)
        ).fetchall()
        db.close()
        if not rows:
            return "✏️ 暂无已存储的记忆"
        lines = ["📝 已记住 (可用 /forget 编号 删除):"]
        for i, r in enumerate(rows, 1):
            lines.append(f"  {i}. {r['mem_key']} = {r['mem_value']}")
        return "\n".join(lines)


class ForgetCommand(Command):
    """记忆删除: /forget 编号 或 /forget 关键词"""

    async def execute(self, event, args):
        key = args.strip()
        if not key:
            return "用法: /forget 编号 (先用 /list-memory 查看)"

        from storage.database import get_db
        db = get_db()
        sk = _get_persona_key(event)

        # Try numeric index first
        try:
            idx = int(key) - 1
            rows = db.execute(
                "SELECT mem_key FROM user_memories WHERE session_key=? ORDER BY created_at", (sk,)
            ).fetchall()
            if 0 <= idx < len(rows):
                real_key = rows[idx]['mem_key']
                db.execute("DELETE FROM user_memories WHERE session_key=? AND mem_key=?", (sk, real_key))
                db.commit()
                db.close()
                return f"✅ 已删除 #{key}: {real_key}"
            db.close()
            return f"❌ 编号 {key} 不存在，一共 {len(rows)} 条"
        except ValueError:
            # Treat as keyword
            db.execute("DELETE FROM user_memories WHERE session_key=? AND mem_key=?", (sk, key))
            db.commit()
            db.close()
            return f"✅ 已删除: {key}"


class LearnCommand(Command):
    """对话学习: /learn → 收藏上一轮对话为人设示例"""
    async def execute(self, event, args):
        from storage.database import get_db
        import uuid
        db = get_db()
        sk = _get_persona_key(event)
        # Get last user+assistant pair
        rows = db.execute(
            "SELECT role, content FROM messages WHERE session_id IN "
            "(SELECT id FROM sessions WHERE account_id=? AND platform=? AND session_key=?) "
            "ORDER BY created_at DESC LIMIT 4",
            (event.account_id, event.platform, event.message.session_id)
        ).fetchall()
        db.close()
        user_msg, bot_reply = None, None
        for r in reversed(rows):
            if r['role'] == 'user': user_msg = r['content']
            elif r['role'] == 'assistant' and user_msg: bot_reply = r['content']; break
        if not user_msg or not bot_reply:
            return "未找到可学习的对话对"
        db = get_db()
        db.execute(
            "INSERT INTO learned_examples (id, session_key, user_msg, bot_reply) VALUES (?,?,?,?)",
            (str(uuid.uuid4()), sk, user_msg, bot_reply)
        )
        db.commit()
        db.close()
        return "✅ 已学习该对话示例"


class ListLearnCommand(Command):
    """已学示例: /list-learn → 查看已学对话"""
    async def execute(self, event, args):
        from storage.database import get_db
        db = get_db()
        sk = _get_persona_key(event)
        rows = db.execute(
            "SELECT user_msg, bot_reply FROM learned_examples WHERE session_key=? ORDER BY created_at DESC LIMIT 10",
            (sk,)
        ).fetchall()
        db.close()
        if not rows:
            return "暂无已学习的对话示例"
        lines = ["📚 已学示例:"]
        for r in rows:
            lines.append(f"  👤 {r['user_msg'][:40]}")
            lines.append(f"  🤖 {r['bot_reply'][:40]}")
        return "\n".join(lines)


class PixivRecommendCommand(Command):
    """Pixiv随机推荐"""
    TOKEN = "YO1FOvVWCU400fK7NFYaW5oJ7nIL5vwUHm2lS4qykKk"
    def __init__(self, llm=None, persona=None): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        try:
            import random, os, httpx
            from pixivpy3 import AppPixivAPI
            api = AppPixivAPI()
            api.auth(refresh_token=self.TOKEN)
            r = api.illust_ranking(mode='day')
            illusts = r.get('illusts', [])
            if not illusts:
                return "未获取到Pixiv日榜数据"
            il = random.choice(illusts[:30])
            return await self._download_and_return(il, event)
        except Exception as e:
            return f"Pixiv获取失败: {e}"

    async def _download_and_return(self, il: dict, event: AstrMessageEvent,
                                    source_label: str = "Pixiv日榜随机") -> list[MessageComponent]:
        import httpx
        pages = il.get('meta_pages', [])
        img_url = pages[0]['image_urls']['original'] if pages else il['image_urls']['large']
        os.makedirs('data/pixiv_cache', exist_ok=True)
        ext = '.jpg' if '.jpg' in img_url else '.png'
        fname = f"pixiv_{il['id']}{ext}"
        fpath = f"data/pixiv_cache/{fname}"
        if not os.path.exists(fpath):
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                resp = await c.get(img_url, headers={'Referer': 'https://www.pixiv.net/'})
                with open(fpath, 'wb') as f:
                    f.write(resp.content)
        pixiv_img = MessageComponent(type=MessageComponentType.IMAGE, data={"file": os.path.abspath(fpath)})
        if self.llm and self.persona:
            tags = ', '.join(t.get('name','') for t in il.get('tags',[])[:3])
            title = il.get('title','')
            author = il.get('user',{}).get('name','')
            bookmark = il.get('total_bookmarks', 0)
            raw = f"{source_label}:\n《{title}》\n画师: {author}\n收藏: {bookmark}\n标签: {tags}"
            chain = await _roleplay_reply(event, raw, "用你的角色语气推荐这张插画，必须保留作品标题、画师、收藏数。", self.llm, self.persona, 512)
            chain.append(pixiv_img)
            return chain
        return [pixiv_img]


class PixivSearchCommand(Command):
    """Pixiv搜索"""
    TOKEN = "YO1FOvVWCU400fK7NFYaW5oJ7nIL5vwUHm2lS4qykKk"
    def __init__(self, llm=None, persona=None): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        if not args.strip():
            return "用法: /pixiv 关键词"
        try:
            from pixivpy3 import AppPixivAPI
            api = AppPixivAPI()
            api.auth(refresh_token=self.TOKEN)
            r = api.search_illust(args.strip(), search_target='partial_match_for_tags')
            illusts = r.get('illusts', [])
            if not illusts:
                return f"未找到 '{args.strip()}' 相关作品"
            il = illusts[0]
            result = await PixivRecommendCommand._download_and_return(
                self, il, event, f"Pixiv搜索 '{args.strip()}'")
            return result
        except Exception as e:
            return f"Pixiv搜索失败: {e}"


class MusicNewCommand(Command):
    """QQ音乐新歌随机推荐: /music-new → 新歌榜随机抽1首"""
    def __init__(self, llm=None, persona=None): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        try:
            import random, httpx
            async with httpx.AsyncClient(timeout=10, headers={'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://y.qq.com'}) as c:
                r = await c.get('https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?topid=27&format=json')
                songs = r.json().get('songlist', [])
                if not songs:
                    return "暂无新歌数据"
                s = random.choice(songs)['data']
                name = s.get('songname', '?')
                singer = ', '.join(si.get('name', '') for si in s.get('singer', []))
                songmid = s.get('songmid', '')
                link = f"https://y.qq.com/n/ryqq/songDetail/{songmid}" if songmid else ""
                album = s.get('albumname', '')

            raw = f"QQ音乐新歌推荐:\n《{name}》- {singer}\n专辑: {album}\n链接: {link}"
            if self.llm and self.persona:
                chain = await _roleplay_reply(event, raw,
                    "用你的角色语气推荐这首歌，必须保留歌名、歌手、链接。先写简短开场白再自然点评。",
                    self.llm, self.persona, 300)
                return chain
            return _resolve_stickers(raw)
        except Exception as e:
            return f"获取失败: {e}"


class MusicHotCommand(Command):
    """QQ音乐热歌榜: /music-hot → top 10"""
    def __init__(self, llm=None, persona=None): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10, headers={'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://y.qq.com'}) as c:
                r = await c.get('https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?topid=26&format=json')
                songs = r.json().get('songlist', [])[:10]
                if not songs:
                    return "暂无热歌数据"

                data_for_llm_lines = []
                data_display_lines = []
                for i, item in enumerate(songs, 1):
                    d = item['data']
                    name = d.get('songname', '?')
                    singer = ', '.join(si.get('name', '') for si in d.get('singer', []))
                    songmid = d.get('songmid', '')
                    link = f"https://y.qq.com/n/ryqq/songDetail/{songmid}" if songmid else ""
                    data_for_llm_lines.append(f"{i}. {name} - {singer}")
                    data_display_lines.append(f"{i}. {name} - {singer}\n   {link}")

            opener = ""
            if self.llm and self.persona:
                opener, _ = await _roleplay_commentary(
                    event, "\n".join(data_for_llm_lines), "QQ音乐热歌榜",
                    self.llm, self.persona, 300)

            parts = [opener] if opener else []
            parts.append("\n".join(data_display_lines))
            return _resolve_stickers("\n\n".join(parts))
        except Exception as e:
            return f"获取失败: {e}"


class MusicSearchCommand(Command):
    """QQ音乐搜索: /music-search 关键词 → 前5条"""
    def __init__(self, llm=None, persona=None): self.llm = llm; self.persona = persona

    async def execute(self, event, args):
        if not args.strip():
            return "用法: /music-search 关键词"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10, headers={'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://y.qq.com'}) as c:
                r = await c.get(
                    f'https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={args.strip()}&format=json&n=5')
                songs = r.json().get('data', {}).get('song', {}).get('list', [])
                if not songs:
                    return f"未找到 '{args.strip()}' 相关歌曲"

                data_for_llm_lines = []
                data_display_lines = []
                for i, s in enumerate(songs, 1):
                    name = s.get('songname', '?')
                    singer = ', '.join(si.get('name', '') for si in s.get('singer', []))
                    songmid = s.get('songmid', '')
                    album = s.get('albumname', '')
                    link = f"https://y.qq.com/n/ryqq/songDetail/{songmid}" if songmid else ""
                    data_for_llm_lines.append(f"{i}. {name} - {singer} ({album})")
                    data_display_lines.append(f"{i}. {name} - {singer} | {album}\n   {link}")

            opener = ""
            if self.llm and self.persona:
                opener, _ = await _roleplay_commentary(
                    event, "\n".join(data_for_llm_lines), f"QQ音乐搜索 '{args.strip()}'",
                    self.llm, self.persona, 300)

            parts = [opener] if opener else []
            parts.append("\n".join(data_display_lines))
            return _resolve_stickers("\n\n".join(parts))
        except Exception as e:
            return f"搜索失败: {e}"


class CommandParser:
    """Per-platform command registry. Each entry: {name: (handler, platforms)}.
    platforms=None → all platforms, platforms=["qq"] → QQ only."""

    def __init__(self, context_manager, llm_client=None, persona_engine=None):
        self._registry: dict[str, tuple[Command, list[str] | None]] = {}

        # Register all commands — add platform filter in the third field
        self.register("/reset",  ResetCommand(context_manager))
        self.register("/new",    NewSessionCommand(context_manager))
        self.register("/status", StatusCommand(context_manager))
        self.register("/search", SearchCommand(llm_client, persona_engine, context_manager))
        self.register("/help",   HelpCommand(self._registry))
        self.register("/vision",             VisionCommand(llm_client, persona_engine), ["qq"])
        self.register("/bilibili-hot",       BilibiliHotCommand(llm_client, persona_engine), ["qq"])
        self.register("/bilibili-trending",  BilibiliTrendingCommand(llm_client, persona_engine), ["qq"])
        self.register("/bilibili-recommend", BilibiliRecommendCommand(llm_client, persona_engine), ["qq"])
        self.register("/remember",     RememberCommand())
        self.register("/list-memory",  ListMemoryCommand())
        self.register("/forget",       ForgetCommand())
        self.register("/learn",             LearnCommand())
        self.register("/pixiv-recommend",   PixivRecommendCommand(llm_client, persona_engine), ["qq"])
        self.register("/pixiv",             PixivSearchCommand(llm_client, persona_engine), ["qq"])
        self.register("/music-new",         MusicNewCommand(llm_client, persona_engine), ["qq"])
        self.register("/music-hot",         MusicHotCommand(llm_client, persona_engine), ["qq"])
        self.register("/music-search",      MusicSearchCommand(llm_client, persona_engine), ["qq"])
        self.register("/list-learn",   ListLearnCommand())

    def register(self, name: str, handler: Command, platforms: list[str] | None = None):
        self._registry[name] = (handler, platforms)

    def list_commands(self, platform: str = None) -> list[dict]:
        """List all commands, optionally filtered by platform"""
        result = []
        for name, (handler, platforms) in self._registry.items():
            if platform is None or platforms is None or platform in platforms:
                result.append({"name": name, "platforms": platforms or "all"})
        return result

    def parse(self, event: AstrMessageEvent):
        msg = (event.get_message_str() or "").strip()
        if not msg or not msg.startswith("/"):
            return None

        parts = msg.split(" ", 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        entry = self._registry.get(cmd)
        if entry:
            handler, platforms = entry
            if platforms is None or event.platform in platforms:
                return handler, args
        return None
