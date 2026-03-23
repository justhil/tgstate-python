import asyncio
import re
from functools import lru_cache
from typing import Any

from .. import database
from ..core.config import Settings, get_settings
from ..events import publish_file_update

try:
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
except ImportError:  # pragma: no cover - 运行时依赖缺失时的兜底。
    TelegramClient = None
    events = None
    StringSession = None

MANIFEST_MAGIC = b"tgstate-blob\n"
MESSAGE_BATCH_SIZE = 100
HISTORY_SYNC_STOP_AFTER_KNOWN = 200
CHUNK_FILENAME_PATTERN = re.compile(r"\.part\d+$")


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
        self._session_mode = "disabled"

    @property
    def enabled(self) -> bool:
        return bool(
            TelegramClient
            and self.settings.TG_API_ID
            and self.settings.TG_API_HASH
            and self.settings.CHANNEL_NAME
        )

    async def start(self) -> bool:
        """启动 Telegram 同步服务。"""
        if self._started:
            return True

        if not self.enabled:
            if not TelegramClient:
                print("Telegram 删除同步未启用: 未安装 telethon。")
            else:
                print("Telegram 删除同步未启用: 缺少 TG_API_ID 或 TG_API_HASH。")
            return False

        history_added = await self._bootstrap_history_once()

        self.client = await self._create_runtime_client()
        if not self.client:
            return False

        self.channel_entity = await self.client.get_entity(self.settings.CHANNEL_NAME)
        self.client.add_event_handler(
            self._handle_message_deleted,
            events.MessageDeleted(chats=self.channel_entity)
        )

        self._started = True
        if self.settings.TELEGRAM_SYNC_SESSION_STRING:
            print(
                f"Telegram 同步服务已启动，运行模式: {self._session_mode}，"
                f"启动时历史回填新增 {history_added} 条记录。"
            )
        else:
            print(
                f"Telegram 同步服务已启动，运行模式: {self._session_mode}。"
                "未配置 TELEGRAM_SYNC_SESSION_STRING，已跳过启动时历史回填。"
            )
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
        self._session_mode = "disabled"

    async def _create_runtime_client(self) -> Any:
        """创建常驻 Bot 会话，用于运行期事件监听。"""
        if not self.settings.BOT_TOKEN:
            print("Telegram 同步服务未启用: 缺少 BOT_TOKEN。")
            return None

        bot_session_name = f"{self.settings.TELEGRAM_SYNC_SESSION}-bot"
        bot_client = TelegramClient(
            bot_session_name,
            self.settings.TG_API_ID,
            self.settings.TG_API_HASH
        )
        await bot_client.start(bot_token=self.settings.BOT_TOKEN)
        self._session_mode = "bot_token"
        print("Telegram 同步服务已切换到 Bot 会话。")
        return bot_client

    async def _bootstrap_history_once(self) -> int:
        """
        启动时使用用户会话执行一次历史回填，完成后立即断开。
        """
        session_string = self.settings.TELEGRAM_SYNC_SESSION_STRING
        if not session_string:
            return 0

        if not StringSession:
            print("Telegram 启动回填未启用: 当前 telethon 版本缺少 StringSession。")
            return 0

        bootstrap_client = TelegramClient(
            StringSession(session_string),
            self.settings.TG_API_ID,
            self.settings.TG_API_HASH
        )

        previous_client = self.client
        previous_channel_entity = self.channel_entity

        try:
            await bootstrap_client.connect()
            if not await bootstrap_client.is_user_authorized():
                print(
                    "Telegram 启动回填未执行: "
                    "TELEGRAM_SYNC_SESSION_STRING 无效或已过期。"
                )
                return 0

            me = await bootstrap_client.get_me()
            if getattr(me, "bot", False):
                print(
                    "Telegram 启动回填未执行: "
                    "TELEGRAM_SYNC_SESSION_STRING 对应的是 Bot 会话。"
                )
                return 0

            self.client = bootstrap_client
            self.channel_entity = await bootstrap_client.get_entity(self.settings.CHANNEL_NAME)
            history_added = await self.sync_history_once()
            await self.reconcile_once()
            print("Telegram 启动回填已完成，准备切换回 Bot 会话。")
            return history_added
        except Exception as exc:
            print(f"Telegram 启动回填失败: {exc}")
            return 0
        finally:
            self.client = previous_client
            self.channel_entity = previous_channel_entity
            await bootstrap_client.disconnect()

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
        for index in range(0, len(message_ids), MESSAGE_BATCH_SIZE):
            batch_ids = message_ids[index:index + MESSAGE_BATCH_SIZE]
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

    async def sync_history_once(self) -> int:
        """
        启动时扫描频道历史，重建数据库中的文件索引。

        - 数据库为空时执行一次全量回填。
        - 数据库已有数据时，只向后扫描到连续命中足够多的已知记录后停止，
          避免每次重启都全量遍历整个频道历史。
        """
        if not self.client or not self.channel_entity:
            return 0

        existing_file_ids = {file["file_id"] for file in database.get_all_files()}
        chunk_message_ids: set[int] = set()
        inserted_count = 0
        known_streak = 0
        warm_start = bool(existing_file_ids)

        async for message in self.client.iter_messages(self.channel_entity):
            history_record = await self._build_history_record(message, chunk_message_ids)
            if history_record is None:
                continue

            file_id = history_record["file_id"]
            if file_id in existing_file_ids:
                known_streak += 1
                if warm_start and known_streak >= HISTORY_SYNC_STOP_AFTER_KNOWN:
                    print(
                        "Telegram 历史回填已命中足够多的连续已知记录，"
                        "提前结束本轮扫描。"
                    )
                    break
                continue

            known_streak = 0
            inserted = database.add_file_metadata(
                filename=history_record["filename"],
                file_id=file_id,
                filesize=history_record["filesize"],
                upload_date=history_record["upload_date"],
            )
            if inserted:
                inserted_count += 1
                existing_file_ids.add(file_id)

        if inserted_count:
            print(f"Telegram 历史回填完成，新增 {inserted_count} 条文件记录。")
        else:
            print("Telegram 历史回填完成，本轮没有新增文件记录。")
        return inserted_count

    async def _build_history_record(
        self,
        message: Any,
        chunk_message_ids: set[int],
    ) -> dict[str, Any] | None:
        """从频道历史消息中提取可落库的文件记录。"""
        if not message or not getattr(message, "id", None):
            return None

        message_id = int(message.id)
        upload_date = self._get_message_upload_date(message)

        if getattr(message, "photo", None):
            file_id = self._extract_bot_file_id(message)
            file_size = self._extract_message_size(message)
            if not file_id or file_size is None:
                return None

            return {
                "filename": f"photo_{message_id}.jpg",
                "file_id": f"{message_id}:{file_id}",
                "filesize": file_size,
                "upload_date": upload_date,
            }

        message_file = getattr(message, "file", None)
        if not message_file or not getattr(message, "document", None):
            return None

        file_name = getattr(message_file, "name", None) or self._build_fallback_filename(
            message_id,
            message_file,
        )
        if not file_name:
            return None

        if file_name.endswith(".manifest"):
            return await self._build_manifest_record(message, upload_date, chunk_message_ids)

        if message_id in chunk_message_ids or CHUNK_FILENAME_PATTERN.search(file_name):
            return None

        file_id = self._extract_bot_file_id(message)
        file_size = self._extract_message_size(message)
        if not file_id or file_size is None:
            return None

        return {
            "filename": file_name,
            "file_id": f"{message_id}:{file_id}",
            "filesize": file_size,
            "upload_date": upload_date,
        }

    async def _build_manifest_record(
        self,
        message: Any,
        upload_date: str | None,
        chunk_message_ids: set[int],
    ) -> dict[str, Any] | None:
        """解析清单文件，恢复大文件的原始文件名和总大小。"""
        file_id = self._extract_bot_file_id(message)
        if not file_id:
            return None

        manifest_blob = await self.client.download_media(message, bytes)
        if not isinstance(manifest_blob, (bytes, bytearray)):
            print(f"警告: 无法读取清单消息 {message.id} 的内容。")
            return None

        if not manifest_blob.startswith(MANIFEST_MAGIC):
            print(f"警告: 清单消息 {message.id} 的内容格式无效。")
            return None

        try:
            lines = manifest_blob.decode("utf-8").strip().splitlines()
        except UnicodeDecodeError:
            print(f"警告: 清单消息 {message.id} 解码失败。")
            return None

        if len(lines) < 2:
            print(f"警告: 清单消息 {message.id} 缺少原始文件名。")
            return None

        original_filename = lines[1].strip() or f"file_{message.id}"
        chunk_ids: list[int] = []
        for line in lines[2:]:
            chunk_entry = line.strip()
            if not chunk_entry:
                continue

            try:
                chunk_message_id = int(chunk_entry.split(":", 1)[0])
            except (ValueError, IndexError):
                print(f"警告: 清单消息 {message.id} 包含无效分块记录: {chunk_entry}")
                continue

            chunk_ids.append(chunk_message_id)

        chunk_message_ids.update(chunk_ids)
        total_size = await self._sum_chunk_sizes(chunk_ids)

        return {
            "filename": original_filename,
            "file_id": f"{message.id}:{file_id}",
            "filesize": total_size,
            "upload_date": upload_date,
        }

    async def _sum_chunk_sizes(self, chunk_ids: list[int]) -> int:
        """按批量读取分块消息，累计大文件总大小。"""
        if not self.client or not self.channel_entity or not chunk_ids:
            return 0

        total_size = 0
        for index in range(0, len(chunk_ids), MESSAGE_BATCH_SIZE):
            batch_ids = chunk_ids[index:index + MESSAGE_BATCH_SIZE]
            messages = await self.client.get_messages(self.channel_entity, ids=batch_ids)
            if not isinstance(messages, list):
                messages = [messages]

            message_map = {
                int(message.id): message
                for message in messages
                if message is not None and getattr(message, "id", None)
            }
            for chunk_id in batch_ids:
                chunk_message = message_map.get(chunk_id)
                chunk_size = self._extract_message_size(chunk_message)
                if chunk_size is None:
                    print(f"警告: 无法解析分块消息 {chunk_id} 的文件大小。")
                    continue
                total_size += chunk_size

        return total_size

    def _extract_bot_file_id(self, message: Any) -> str | None:
        """提取 Telethon 消息中的 Bot API 风格 file_id。"""
        message_file = getattr(message, "file", None)
        file_id = getattr(message_file, "id", None)
        return str(file_id) if file_id else None

    def _extract_message_size(self, message: Any) -> int | None:
        """提取消息附件大小。"""
        if not message:
            return None

        message_file = getattr(message, "file", None)
        file_size = getattr(message_file, "size", None)
        if file_size is None:
            return None

        try:
            return int(file_size)
        except (TypeError, ValueError):
            return None

    def _build_fallback_filename(self, message_id: int, message_file: Any) -> str:
        """文件名缺失时，根据扩展名构造兜底名称。"""
        extension = getattr(message_file, "ext", None) or ""
        return f"document_{message_id}{extension}"

    def _get_message_upload_date(self, message: Any) -> str | None:
        """提取消息时间，写回数据库后保留原始排序。"""
        message_date = getattr(message, "date", None)
        if message_date is None:
            return None

        return message_date.isoformat()

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
