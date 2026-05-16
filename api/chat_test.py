import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _get_components(ws):
    return (ws.app.state.context_manager,
            ws.app.state.persona_engine,
            ws.app.state.llm_client,
            ws.app.state.command_parser)


@router.websocket("/ws/chat-test")
async def chat_test(ws: WebSocket):
    await ws.accept()

    ctx_mgr, persona_engine, llm_client, cmd_parser = _get_components(ws)

    # In-memory session for test (not persisted)
    from models.session import Session, Message
    from datetime import datetime

    test_session_id = str(uuid.uuid4())
    test_messages: list[dict] = []

    fake_session = Session(
        id=test_session_id, account_id="test", platform="web",
        session_key="chat_test", created_at=datetime.now(),
        last_active_at=datetime.now(), is_active=True
    )

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            action = data.get("action", "send")

            if action == "command":
                cmd = data.get("command", "")
                handler, args = cmd_parser.commands.get(cmd, (None, ""))
                if handler:
                    # Create a minimal event for command execution
                    from models.message import AstrMessageEvent, AstrBotMessage, MessageType
                    fake_event = AstrMessageEvent(
                        event_id=str(uuid.uuid4()), account_id="test", platform="web",
                        message=AstrBotMessage(
                            message_str=cmd, message_chain=[], type=MessageType.PRIVATE,
                            session_id="chat_test"
                        )
                    )
                    reply = await handler.execute(fake_event, args)
                    await ws.send_json({"type": "command_result", "message": reply})
                continue

            message = data.get("message", "")
            persona_id = data.get("persona_id")
            provider_id = data.get("provider_id")

            # Load persona
            from storage.database import get_db
            persona = None
            try:
                db = get_db()
                if persona_id:
                    row = db.execute("SELECT * FROM personas WHERE id=?", (persona_id,)).fetchone()
                else:
                    row = db.execute("SELECT * FROM personas WHERE is_active=1 LIMIT 1").fetchone()
                if row:
                    from core.persona import Persona
                    persona = Persona(**dict(row))
                db.close()
            except Exception:
                pass

            if not persona:
                from core.persona import Persona
                persona = Persona(id="test", name="Test", description="测试角色")

            # Load provider
            from core.llm import ProviderConfig
            provider = None
            try:
                db = get_db()
                if provider_id:
                    prow = db.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
                else:
                    prow = db.execute("SELECT * FROM providers WHERE category='chat' AND is_default=1 LIMIT 1").fetchone()
                if prow:
                    p = dict(prow)
                    provider = ProviderConfig(
                        id=p['id'], name=p['name'], model=p['model'],
                        api_key=_decrypt(p.get('api_key_enc', '')),
                        base_url=p['base_url'], temperature=p['temperature'],
                        max_tokens=p['max_tokens'], is_default=bool(p['is_default'])
                    )
                db.close()
            except Exception:
                pass

            if not provider:
                await ws.send_json({"type": "error", "message": "未配置模型"})
                continue

            # Add user message
            test_messages.append({"role": "user", "content": message})

            # Build system prompt
            system_prompt = persona_engine.build_system_prompt(persona)

            # Build LLM messages
            llm_messages = [{"role": "system", "content": system_prompt}]
            # Sliding window on test messages (keep last 40)
            llm_messages.extend(test_messages[-40:])

            # Stream
            full_text = []
            try:
                async for token in llm_client.chat_stream(llm_messages, provider):
                    full_text.append(token)
                    await ws.send_json({"type": "chunk", "content": token})
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                continue

            reply = "".join(full_text)
            reasoning = llm_client.last_reasoning
            asst_msg = {"role": "assistant", "content": reply}
            if reasoning:
                asst_msg["reasoning_content"] = reasoning
            else:
                asst_msg["reasoning_content"] = ""
            test_messages.append(asst_msg)
            await ws.send_json({"type": "done", "full_text": reply})

    except WebSocketDisconnect:
        pass


def _decrypt(encrypted: str) -> str:
    from config import load_config
    config = load_config()
    if config.secret_key:
        try:
            from cryptography.fernet import Fernet
            f = Fernet(config.secret_key.encode() if len(config.secret_key) == 44
                       else Fernet.generate_key())
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            return encrypted
    return encrypted
