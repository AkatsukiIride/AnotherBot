import asyncio
import json
import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import load_config
from storage.database import init_db, get_db
from core.queue import MessageQueue
from core.context import ContextManager
from core.command import CommandParser
from core.persona.engine import PersonaEngine
from core.llm.client import LLMClient
from core.router import MessageRouter
from adapters.manager import AdapterManager
from api.router import api_router
from api.chat_test import router as ws_router
from models.message import (
    AstrMessageEvent, AstrBotMessage, MessageType,
    MessageMember,
)


def setup_logging(level: str = "INFO"):
    import os
    os.makedirs("data/logs", exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("data/logs/anotherbot.log", encoding="utf-8"),
        ],
    )


def deserialize_event(event_json: str) -> AstrMessageEvent:
    data = json.loads(event_json)
    msg_data = data["message"]
    sender_data = msg_data.get("sender")
    sender = MessageMember(user_id=sender_data["user_id"], name=sender_data["name"]) if sender_data else None
    msg = AstrBotMessage(
        message_str=msg_data["message_str"],
        message_chain=[],
        type=MessageType(msg_data["type"]),
        session_id=msg_data["session_id"],
        group_id=msg_data.get("group_id"),
        sender=sender,
        is_at_bot=msg_data.get("is_at_bot", False),
        raw_message=msg_data.get("raw_message"),
    )
    return AstrMessageEvent(
        event_id=data["event_id"],
        account_id=data["account_id"],
        platform=data["platform"],
        message=msg,
    )


app = FastAPI(title="AnotherBot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(ws_router)

# Global instances
config = load_config()
queue = MessageQueue()
ctx_mgr = ContextManager()
persona_engine = PersonaEngine()
llm_client = LLMClient()
cmd_parser = CommandParser(ctx_mgr, llm_client, persona_engine)
adapter_mgr = AdapterManager(queue)
router = MessageRouter(ctx_mgr, persona_engine, llm_client, cmd_parser, adapter_mgr)

# Expose to API via app.state
app.state.adapter_manager = adapter_mgr
app.state.context_manager = ctx_mgr
app.state.persona_engine = persona_engine
app.state.llm_client = llm_client
app.state.command_parser = cmd_parser


async def worker_loop():
    """Message queue consumer"""
    logger = logging.getLogger("worker")
    while True:
        batch = await queue.dequeue_batch(10)
        for item in batch:
            try:
                event = deserialize_event(item['event_json'])
                await router.route(event)
                await queue.mark_done(item['id'])
            except Exception as e:
                logger.error(f"处理消息失败: {e}")
                await queue.mark_failed(item['id'])
        await asyncio.sleep(0.5)


async def cleanup_loop():
    """Periodic cleanup"""
    logger = logging.getLogger("cleanup")
    import datetime as dt
    last_daily = dt.date.today()
    while True:
        await asyncio.sleep(600)
        try:
            cleaned = await queue.cleanup_old()
            expired = await ctx_mgr.cleanup_expired(30)
            if cleaned or expired:
                logger.info(f"清理: {cleaned} 条队列消息, {expired} 个过期会话")

            # Daily midnight cleanup: purge yesterday's data
            today = dt.date.today()
            if today != last_daily:
                from storage.database import get_db
                db = get_db()
                db.execute("DELETE FROM messages WHERE date(created_at) < date('now')")
                db.execute("DELETE FROM sessions WHERE is_active=0 AND date(last_active_at) < date('now')")
                db.commit()
                db.close()
                last_daily = today
                logger.info("每日数据清理完成")
        except Exception as e:
            logger.error(f"清理出错: {e}")


@app.on_event("startup")
async def startup():
    setup_logging(config.log_level)
    logger = logging.getLogger("anotherbot")
    logger.info("Starting AnotherBot...")

    init_db()
    logger.info("Database initialized")

    recovered = await queue.recover_on_startup()
    if recovered:
        logger.info(f"Recovered {recovered} unprocessed messages from queue")

    # Start enabled accounts
    db = get_db()
    accounts = db.execute("SELECT * FROM accounts WHERE enabled=1").fetchall()
    db.close()
    for acc in accounts:
        acc_dict = dict(acc)
        try:
            await adapter_mgr.start_account(acc_dict)
            logger.info(f"Account '{acc_dict['name']}' started")
        except Exception as e:
            logger.error(f"Failed to start account '{acc_dict['name']}': {e}")

    # Background tasks
    asyncio.create_task(worker_loop())
    asyncio.create_task(cleanup_loop())
    logger.info("AnotherBot ready")


@app.on_event("shutdown")
async def shutdown():
    logger = logging.getLogger("anotherbot")
    logger.info("Shutting down...")
    await adapter_mgr.shutdown_all()
    logger.info("AnotherBot stopped")


def main():
    setup_logging(config.log_level)
    logger = logging.getLogger("anotherbot")

    if "--generate-key" in sys.argv:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        print(f"\nANOTHERBOT_SECRET_KEY={key}\n")
        print("请将以上密钥设为环境变量 ANOTHERBOT_SECRET_KEY")
        return

    logger.info(f"Starting on http://{config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level.lower())


if __name__ == "__main__":
    main()
