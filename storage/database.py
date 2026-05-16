import sqlite3
import os

from config import load_config

_config = load_config()
DB_PATH = _config.db_path


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    # Add reasoning_content column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT DEFAULT ''")
    except Exception:
        pass  # Column already exists
    # Add token_count column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN token_count INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platforms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            adapter_class TEXT NOT NULL,
            config_schema TEXT NOT NULL DEFAULT '{}',
            requires_account INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        INSERT OR IGNORE INTO platforms VALUES
            ('qq', 'QQ', 'QQAdapter',
             '{"protocol":"onebot_v11","ws_port":3001,"bot_qq":""}',
             1, 1),
            ('desktop_pet', '桌宠', 'DesktopPetAdapter',
             '{"window_title":"小助手"}',
             0, 0),
            ('bilibili', 'B站', 'BilibiliAdapter',
             '{"sessdata":"","bili_jct":"","buvid3":"","bot_name":"","live_room_ids":[],"live_enabled":false,"comment_enabled":false,"session_enabled":false}',
             1, 0);

        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            personality TEXT DEFAULT '',
            scenario TEXT DEFAULT '',
            first_message TEXT DEFAULT '',
            example_dialogue TEXT DEFAULT '',
            custom_prompt TEXT DEFAULT '',
            post_instructions TEXT DEFAULT '',
            avatar_path TEXT DEFAULT '',
            is_active INTEGER DEFAULT 0,
            author TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider_type TEXT NOT NULL DEFAULT 'openai_compatible',
            category TEXT NOT NULL DEFAULT 'chat',
            model TEXT NOT NULL,
            api_key_enc TEXT NOT NULL,
            base_url TEXT NOT NULL,
            temperature REAL DEFAULT 0.8,
            max_tokens INTEGER DEFAULT 512,
            is_default INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            platform_id TEXT NOT NULL REFERENCES platforms(id),
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 0,
            config_json TEXT NOT NULL DEFAULT '{}',
            persona_id TEXT REFERENCES personas(id),
            chat_provider_id TEXT REFERENCES providers(id),
            vision_provider_id TEXT REFERENCES providers(id),
            favorite_sticker_codes TEXT DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id),
            platform TEXT NOT NULL,
            session_key TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1,
            UNIQUE(account_id, platform, session_key)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            sender_id TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            content TEXT NOT NULL,
            reasoning_content TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at);

        CREATE TABLE IF NOT EXISTS stickers (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            description TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT 'image/png',
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS message_queue (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id),
            event_json TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_mq_status
            ON message_queue(status, created_at);

        CREATE TABLE IF NOT EXISTS bili_replied (
            item_id TEXT PRIMARY KEY
        );
    """)
    conn.commit()
    conn.close()
