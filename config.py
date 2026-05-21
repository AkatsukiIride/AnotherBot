import os
from dataclasses import dataclass, field


@dataclass
class AppConfig:
    db_path: str = "data/anotherbot.db"
    data_dir: str = "data"
    host: str = "127.0.0.1"
    port: int = 8080
    secret_key: str = ""
    log_level: str = "INFO"
    sticker_limit: int = 500
    pixiv_token: str = ""


def load_config() -> AppConfig:
    return AppConfig(
        db_path=os.environ.get("ANOTHERBOT_DB", "data/anotherbot.db"),
        data_dir=os.environ.get("ANOTHERBOT_DATA", "data"),
        host=os.environ.get("ANOTHERBOT_HOST", "127.0.0.1"),
        port=int(os.environ.get("ANOTHERBOT_PORT", "8080")),
        secret_key=os.environ.get("ANOTHERBOT_SECRET_KEY", ""),
        log_level=os.environ.get("ANOTHERBOT_LOG_LEVEL", "INFO"),
        sticker_limit=int(os.environ.get("ANOTHERBOT_STICKER_LIMIT", "500")),
        pixiv_token=os.environ.get("ANOTHERBOT_PIXIV_TOKEN", ""),
    )
