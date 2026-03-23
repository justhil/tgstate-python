import asyncio
from functools import lru_cache
from typing import Any

from .. import database
from ..core.config import Settings, get_settings
from ..events import publish_file_update

try:
    from telethon import TelegramClient, events
except ImportError:  # pragma: no cover - 运行时依赖缺失时的兜底。
    TelegramClient = None
    events = None


class TelegramSyncService:
    """
    使用 MTProto 对账 Telegram 频道状态，补齐 Bot API 无法感知的删除事件。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Any = None
        self.channel_entity: Any = None
        self._reconcile_task: asyncio.Task | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return bool(
            TelegramClient
            and self.settings.TG_API_ID
            and self.settings.TG_API_HASH
            and self.settings.BOT_TOKEN
            and self.settings.CHANNEL_NAME
        )

    async def start(self) -> bool:
        """启动删除同步服务。"""
        if self._started:
            return True

        if not self.enabled:
            if not TelegramClient:
                print("Telegram 删除同步未启用: 未安装 telethon。")
            else:
                print("Telegram 删除同步未启用: 缺少 TG_API_ID 或 TG_API_HASH。")
            return False

        self.client = TelegramClient(
            self.settings.TELEGRAM_SYNC_SESSION,
            self.settings.TG_API_ID,
            self.settings.TG_API_HASH
        )
        await self.client.start(bot_token=self.settings.BOT_TOKEN)
        self.channel_entity = await self.client.get_entity(self.settings.CHANNEL_NAME)
        self.client.add_event_handler(
            self._handle_message_deleted,
            events.MessageDeleted(chats=self.channel_entity)
        )

        await self.reconcile_once()
        if self.settings.TELEGRAM_RECONCILE_INTERVAL > 0:
            self._reconcile_task = asyncio.create_task(self._reconcile_loop())

        self._started = True
        print("Telegram 删除同步服务已启动。")
        return True

    async def stop(self) -> None:
        """停止删除同步服务。"""
        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass
            self._reconcile_task = None

        if self.client:
            await self.client.disconnect()
            self.client = None

        self.channel_entity = None
        self._started = False

    async def reconcile_once(self) -> int:
        """主动对账数据库与频道主消息是否一致。"""
        if not self.client or not self.channel_entity:
            return 0

        files = database.get_all_files()
        message_ids: list[int] = []
        for file in files:
            try:
                message_ids.append(int(str(file["file_id"]).split(":", 1)[0]))
            except (ValueError, IndexError):
                print(f"警告: 跳过无效 file_id: {file['file_id']}")

        removed_file_ids: list[str] = []
        for index in range(0, len(message_ids), 100):
            batch_ids = message_ids[index:index + 100]
            messages = await self.client.get_messages(self.channel_entity, ids=batch_ids)
            if not isinstance(messages, list):
                messages = [messages]

            for message_id, message in zip(batch_ids, messages):
                if message is None:
                    deleted_file_id = database.delete_file_by_message_id(message_id)
                    if deleted_file_id:
                        removed_file_ids.append(deleted_file_id)

        for file_id in removed_file_ids:
            await publish_file_update({
                "action": "delete",
                "file_id": file_id
            })

        if removed_file_ids:
            print(f"Telegram 删除对账完成，本轮同步删除 {len(removed_file_ids)} 条记录。")
        return len(removed_file_ids)

    async def _reconcile_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.settings.TELEGRAM_RECONCILE_INTERVAL)
                await self.reconcile_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"Telegram 删除对账失败: {exc}")

    async def _handle_message_deleted(self, event: Any) -> None:
        deleted_ids = getattr(event, "deleted_ids", None) or getattr(event, "message_ids", None) or []
        for message_id in deleted_ids:
            deleted_file_id = database.delete_file_by_message_id(int(message_id))
            if deleted_file_id:
                await publish_file_update(
                    {
                        "action": "delete",
                        "file_id": deleted_file_id
                    }
                )


@lru_cache()
def get_telegram_sync_service() -> TelegramSyncService:
    """Telegram 删除同步服务工厂。"""
    return TelegramSyncService(settings=get_settings())
