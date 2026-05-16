import json
import importlib
import logging

from storage.database import get_db

logger = logging.getLogger(__name__)


class PortConflictError(Exception):
    pass


class AdapterManager:
    """Manages lifecycle of all account adapter instances"""

    def __init__(self, queue):
        self.instances: dict[str, object] = {}
        self.queue = queue

    async def start_account(self, account: dict) -> None:
        account_id = account['id']
        platform_id = account['platform_id']

        db = get_db()
        platform = db.execute(
            "SELECT adapter_class FROM platforms WHERE id=?", (platform_id,)
        ).fetchone()
        db.close()

        if not platform:
            raise ValueError(f"Unknown platform: {platform_id}")

        cls_name = platform['adapter_class']

        # Dynamic import: adapters.{platform_id}.adapter.{ClassName}
        mod = importlib.import_module(f"adapters.{platform_id}.adapter")
        cls = getattr(mod, cls_name)

        config = json.loads(account['config_json'])

        # Port conflict check only for QQ/WebSocket-based platforms
        if 'ws_port' in config and platform_id == 'qq' and config['ws_port']:
            used_ports = []
            for inst in self.instances.values():
                cfg = inst.config if hasattr(inst, 'config') else {}
                if 'ws_port' in cfg and cfg['ws_port']:
                    used_ports.append(cfg['ws_port'])
            if config['ws_port'] in used_ports:
                raise PortConflictError(
                    f"端口 {config['ws_port']} 已被占用，请换一个"
                )

        adapter = cls(account_id, config, self.queue)
        await adapter.start()
        self.instances[account_id] = adapter

    async def stop_account(self, account_id: str) -> None:
        if account_id in self.instances:
            await self.instances[account_id].stop()
            del self.instances[account_id]

    async def restart_account(self, account_id: str) -> None:
        if account_id in self.instances:
            await self.stop_account(account_id)
            db = get_db()
            account = db.execute(
                "SELECT * FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            db.close()
            if account:
                await self.start_account(dict(account))

    def get_adapter(self, account_id: str):
        return self.instances.get(account_id)

    async def shutdown_all(self) -> None:
        for account_id in list(self.instances.keys()):
            await self.stop_account(account_id)
