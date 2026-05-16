import asyncio
import json
import os
import re

from models.message import (
    AstrMessageEvent, AstrBotMessage, MessageComponent,
    MessageType, MessageComponentType, MessageMember,
)
from core.context import ContextManager
from core.command import CommandParser
from core.persona.engine import PersonaEngine
from core.llm.client import LLMClient
from core.llm import ProviderConfig
from core.persona import Persona
from storage.database import get_db
from api.system import broadcast_event


class MessageRouter:
    """Core message router — dispatches messages through the pipeline"""

    def __init__(self, context_manager: ContextManager,
                 persona_engine: PersonaEngine,
                 llm_client: LLMClient,
                 command_parser: CommandParser,
                 adapter_manager):
        self.ctx = context_manager
        self.persona = persona_engine
        self.llm = llm_client
        self.cmd_parser = command_parser
        self.adapters = adapter_manager

    async def route(self, event: AstrMessageEvent) -> None:
        # 1. Check for command
        result = self.cmd_parser.parse(event)
        if result:
            handler, args = result
            reply = await handler.execute(event, args)
            adapter = self.adapters.get_adapter(event.account_id)
            if adapter:
                await adapter.send(event, [MessageComponent(
                    type=MessageComponentType.TEXT,
                    data={"text": reply}
                )])
            return

        # 2. Load account config (needed for SSE display)
        account = self._get_account(event.account_id)
        if not account:
            return

        # 3. Broadcast ALL messages to Dashboard SSE (even if Bot doesn't reply)
        broadcast_event("message", {
            "account_name": account.get('name', ''),
            "platform": event.platform,
            "session_key": self._session_label(event),
            "sender": event.message.sender.name if event.message.sender else "",
            "content": event.message.message_str,
            "direction": "received",
            "is_at_bot": event.message.is_at_bot,
            "timestamp": event.created_at.strftime("%H:%M:%S"),
        })
        # 4. Gate: only react to @Bot or private messages
        if not (event.message.is_at_bot or event.message.type == MessageType.PRIVATE):
            return

        # 5. Load persona (account override → system default)
        persona = self._get_persona(account)

        # 5. Load provider (account override → system default)
        provider = self._get_provider(account, 'chat')
        if not provider:
            adapter = self.adapters.get_adapter(event.account_id)
            if adapter:
                await adapter.send(event, [MessageComponent(
                    type=MessageComponentType.TEXT,
                    data={"text": "⚠️ 未配置 AI 模型，请先在 Web 管理台设置。"}
                )])
            return

        # 6. Context — sliding window (params from account config)
        ctx_config = json.loads(account.get('config_json', '{}'))
        max_turns = ctx_config.get('context_max_turns', 20)
        ttl_minutes = ctx_config.get('context_ttl_minutes', 30)

        session = await self.ctx.get_or_create_session(
            event.account_id, event.platform, event.message.session_id
        )

        # Build context-aware user message with platform prefix
        context_prefix = self._build_context_prefix(event, account)
        user_content = f"{context_prefix}: {event.message.message_str}" if context_prefix else event.message.message_str

        await self.ctx.add_message(
            session, "user", user_content,
            event.message.sender.user_id if event.message.sender else "",
            event.message.sender.name if event.message.sender else ""
        )

        context_msgs = await self.ctx.build_context(session, max_turns, ttl_minutes)

        # 7. System prompt — with platform-specific constraints
        platform_key = event.platform
        if event.platform == "bilibili" and event.message.raw_message:
            bili_source = event.message.raw_message.get('_bili_source', 'live')
            platform_key = f"bilibili_{bili_source}"
        system_prompt = self.persona.build_system_prompt(persona, platform_key)
        # Inject sticker list into <!-- STICKERS --> or <!-- STICKERS:EM0001,EM0002 --> placeholders
        import re
        def replace_sticker_block(m):
            spec = m.group(1)  # None or ":EM0001,EM0002"
            codes = None
            if spec:
                codes = [c.strip() for c in spec.lstrip(':').split(',') if c.strip().startswith('EM')]
            hint = self._build_sticker_hint(codes)
            return hint if hint else "\n\n(当前没有可用表情包，请勿引用任何表情包编号)"
        system_prompt = re.sub(
            r'<!-- STICKERS(:[A-Z0-9,]+)? -->',
            replace_sticker_block, system_prompt
        )

        # 8. Build messages for LLM
        messages = [{"role": "system", "content": system_prompt}]
        for msg in context_msgs:
            entry = {"role": msg.role, "content": msg.content}
            if msg.role == "assistant" and msg.reasoning_content:
                entry["reasoning_content"] = msg.reasoning_content
            elif msg.role == "assistant":
                entry["reasoning_content"] = ""
            messages.append(entry)

        # 9. Call LLM (stream → buffer → send once)
        full_reply = []
        try:
            async for token in self.llm.chat_stream(messages, provider):
                full_reply.append(token)
        except Exception:
            full_reply = ["唔...我好像卡住了，再试一次？"]

        reply_text = "".join(full_reply)
        reply_reasoning = self.llm.last_reasoning

        # 10. Token counting
        usage = self.llm.last_usage.get("total_tokens", 0)
        if usage <= 0:
            usage = max(1, len(reply_text) // 2)  # Fallback estimation

        # 11. Save reply (with reasoning_content + token_count)
        await self.ctx.add_message_with_reasoning(
            session, "assistant", reply_text, reply_reasoning,
            token_count=usage,
        )

        # 12. Build reply chain and send
        # Clean hallucinated non-EM sticker formats + Markdown images
        clean_text = re.sub(r'\{[^}]*sticker[^}]*\}', '', reply_text)
        clean_text = re.sub(r'\[sticker[^\]]*\]', '', clean_text)
        clean_text = re.sub(r'!\[.*?\]\(https?://[^\s)]+\)', '', clean_text)
        reply_chain = self._build_reply_chain(clean_text)
        # B站: strip all images (danmaku/comments don't support custom images)
        if event.platform == 'bilibili':
            reply_chain = [c for c in reply_chain if c.type != MessageComponentType.IMAGE]
        display_text = re.sub(r'\[?EM\d{4}\]?', '', clean_text).strip()

        adapter = self.adapters.get_adapter(event.account_id)
        if adapter:
            # Split chain: send text parts as one message, each image separately
            text_parts = [c for c in reply_chain if c.type == MessageComponentType.TEXT]
            image_parts = [c for c in reply_chain if c.type == MessageComponentType.IMAGE]

            if text_parts:
                await adapter.send(event, text_parts)
                # Brief pause between messages for natural feel
                await asyncio.sleep(0.3)
            for img in image_parts:
                await adapter.send(event, [img])
                await asyncio.sleep(0.3)

            # Emit SSE: bot reply sent (clean text)
            broadcast_event("message", {
                "account_name": account.get('name', ''),
                "content": display_text or reply_text,
                "direction": "sent",
                "timestamp": event.created_at.strftime("%H:%M:%S"),
            })

    def _build_context_prefix(self, event: AstrMessageEvent, account: dict) -> str:
        """Build platform context prefix for user messages"""
        if event.message.type == MessageType.GROUP:
            return f"[群聊:{event.message.group_id}] {event.message.sender.name if event.message.sender else '用户'}"
        return f"[私聊] {event.message.sender.name if event.message.sender else '用户'}"

    def _build_reply_chain(self, text: str) -> list:
        """Parse LLM reply for [EMxxxx] codes and build message chain with images.
        Matches both bracketed [EM0001] and bare EM0001 at word boundaries."""
        # Match: [EM0001] (bracketed) or standalone EM0001 (bare, word boundary)
        pattern = r'(?:\[)?(EM\d{4})(?:\])?'
        parts = re.split(pattern, text)
        chain = []
        for i, part in enumerate(parts):
            if i % 2 == 1:  # Odd = potential sticker code
                code = part
                db = get_db()
                row = db.execute(
                    "SELECT file_path FROM stickers WHERE code=?", (code,)
                ).fetchone()
                db.close()
                if row and os.path.exists(row['file_path']):
                    abs_path = os.path.abspath(row['file_path'])
                    chain.append(MessageComponent(
                        type=MessageComponentType.IMAGE,
                        data={"file": abs_path}
                    ))
                    continue  # Valid sticker → image, skip text
                # Not a valid sticker → treat as regular text
                chain.append(MessageComponent(
                    type=MessageComponentType.TEXT,
                    data={"text": part}
                ))
            elif part.strip():  # Even = regular text
                chain.append(MessageComponent(
                    type=MessageComponentType.TEXT,
                    data={"text": part}
                ))
        return chain if chain else [MessageComponent(
            type=MessageComponentType.TEXT, data={"text": text}
        )]

    def _build_sticker_hint(self, codes: list[str] | None = None) -> str:
        """Build sticker list for System Prompt injection.
        If codes specified, only include those stickers."""
        db = get_db()
        if codes:
            placeholders = ','.join('?' * len(codes))
            rows = db.execute(
                f"SELECT code, description FROM stickers WHERE description != '' AND code IN ({placeholders}) LIMIT 30",
                codes
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT code, description FROM stickers WHERE description != '' LIMIT 30"
            ).fetchall()
        db.close()
        if not rows:
            return ""
        parts = ["\n\n---\n【表情包引用规则】只能使用以下编号，格式为 EM+4位数字（如EM0001）。直接放在句末，不要加花括号、sticker前缀或任何其他格式。禁止使用 {sticker:xxx} 或其他自创格式。"]
        for r in rows:
            desc = r['description']
            if len(desc) > 60:
                desc = desc[:60] + "..."
            parts.append(f"[{r['code']}] | {desc}")
        parts.append("---")
        return "\n".join(parts)

    def _session_label(self, event: AstrMessageEvent) -> str:
        """Human-readable session label for SSE display"""
        if event.message.type == MessageType.GROUP:
            return f"群:{event.message.group_id}"
        return "私聊"

    def _get_account(self, account_id: str) -> dict | None:
        db = get_db()
        row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        db.close()
        return dict(row) if row else None

    def _get_persona(self, account: dict) -> Persona:
        db = get_db()
        persona_id = account.get('persona_id')
        if persona_id:
            row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
            if row:
                db.close()
                return Persona(**dict(row))
        # fallback to system active
        row = db.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
        db.close()
        if row:
            return Persona(**dict(row))
        return Persona(id="default", name="小助手", description="一个友好的AI助手")

    def _get_provider(self, account: dict, category: str) -> ProviderConfig | None:
        db = get_db()
        provider_id = account.get(f'{category}_provider_id')
        if provider_id:
            row = db.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
            if row:
                db.close()
                return self._row_to_provider(dict(row))
        # fallback to default for category
        row = db.execute(
            "SELECT * FROM providers WHERE category=? AND is_default=1 LIMIT 1",
            (category,)
        ).fetchone()
        db.close()
        if row:
            return self._row_to_provider(dict(row))
        return None

    def _row_to_provider(self, row: dict) -> ProviderConfig:
        from cryptography.fernet import Fernet
        from config import load_config
        config = load_config()
        if config.secret_key:
            try:
                f = Fernet(config.secret_key.encode() if len(config.secret_key) == 44
                           else Fernet.generate_key())
                api_key = f.decrypt(row['api_key_enc'].encode()).decode()
            except Exception:
                api_key = row['api_key_enc']
        else:
            api_key = row['api_key_enc']
        return ProviderConfig(
            id=row['id'], name=row['name'],
            provider_type=row['provider_type'], category=row['category'],
            model=row['model'], api_key=api_key, base_url=row['base_url'],
            temperature=row['temperature'], max_tokens=row['max_tokens'],
            is_default=bool(row['is_default'])
        )
