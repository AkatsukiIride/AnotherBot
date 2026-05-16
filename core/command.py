from abc import ABC, abstractmethod

from models.message import AstrMessageEvent


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
    def __init__(self):
        self.text = (
            "/reset   - 清空当前对话上下文\n"
            "/new     - 结束当前对话\n"
            "/status  - 查看上下文状态\n"
            "/search  - 联网搜索 (如 /search 今天天气)\n"
            "/help    - 显示此帮助"
        )

    async def execute(self, event, args):
        return f"\U0001f4cb 可用指令:\n{self.text}"


class CommandParser:
    def __init__(self, context_manager, llm_client=None, persona_engine=None):
        self.commands = {
            "/reset":  ResetCommand(context_manager),
            "/new":    NewSessionCommand(context_manager),
            "/status": StatusCommand(context_manager),
            "/search": SearchCommand(llm_client, persona_engine, context_manager),
            "/help":   HelpCommand(),
        }

    def parse(self, event: AstrMessageEvent):
        msg = (event.get_message_str() or "").strip()
        if not msg or not msg.startswith("/"):
            return None

        parts = msg.split(" ", 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler = self.commands.get(cmd)
        if handler:
            return handler, args
        return None
