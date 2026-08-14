import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import database
from app.services.telegram_service import CHUNK_SIZE_BYTES, TelegramService
from app.services.telegram_sync_service import TelegramSyncService


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name, "files.db")
        self.database_patch = patch.object(database, "DATABASE_URL", str(self.database_path))
        self.database_patch.start()
        database.init_db()

    def tearDown(self):
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_should_return_only_requested_file_page(self):
        for index in range(5):
            database.add_file_metadata(
                filename=f"file-{index}.txt",
                file_id=f"{index}:id-{index}",
                filesize=index,
                upload_date=f"2026-01-0{index + 1}T00:00:00",
            )

        page = database.get_files_page(limit=2, offset=1)

        self.assertEqual([item["filename"] for item in page], ["file-3.txt", "file-2.txt"])
        self.assertEqual(database.count_files(), 5)

    def test_should_page_images_before_applying_limit(self):
        for index in range(30):
            database.add_file_metadata(
                filename=f"image-{index}.png",
                file_id=f"image-{index}:id",
                filesize=index,
                upload_date=f"2026-02-{(index % 28) + 1:02}T00:00:00",
            )
        for index in range(30):
            database.add_file_metadata(
                filename=f"document-{index}.txt",
                file_id=f"document-{index}:id",
                filesize=index,
                upload_date=f"2026-01-{(index % 28) + 1:02}T00:00:00",
            )

        images = database.get_files_page(limit=50, images_only=True)

        self.assertEqual(len(images), 30)
        self.assertTrue(all(item["filename"].endswith(".png") for item in images))
        self.assertEqual(database.count_files(images_only=True), 30)

    def test_should_create_upload_date_index(self):
        connection = database.get_db_connection()
        try:
            indexes = {
                row["name"]
                for row in connection.execute("PRAGMA index_list('files')").fetchall()
            }
        finally:
            connection.close()

        self.assertIn("idx_files_upload_date_id", indexes)

    async def test_should_upload_large_file_from_bounded_file_views(self):
        settings = SimpleNamespace(BOT_TOKEN="dummy", CHANNEL_NAME="@dummy")
        service = TelegramService(settings)
        observed_read_sizes = []
        message_id = 0

        async def send_document(*, document, **kwargs):
            nonlocal message_id
            message_id += 1
            if kwargs["filename"].endswith(".manifest"):
                return SimpleNamespace(
                    message_id=message_id,
                    document=SimpleNamespace(file_id=f"manifest-{message_id}"),
                )

            observed_read_sizes.append(len(document.input_file_content.read()))
            return SimpleNamespace(
                message_id=message_id,
                document=SimpleNamespace(file_id=f"chunk-{message_id}"),
            )

        service.bot = SimpleNamespace(send_document=AsyncMock(side_effect=send_document))

        with tempfile.NamedTemporaryFile(delete=False) as file:
            file.write(b"x" * (CHUNK_SIZE_BYTES + 17))
            file_path = file.name

        try:
            with patch("app.services.telegram_service.database.add_file_metadata"):
                file_id = await service.upload_file(file_path, "large.bin")
        finally:
            os.unlink(file_path)

        self.assertTrue(file_id)
        self.assertEqual(observed_read_sizes, [CHUNK_SIZE_BYTES, 17])
        self.assertTrue(all(size <= CHUNK_SIZE_BYTES for size in observed_read_sizes))

    async def test_should_prefetch_next_chunk_url_during_download(self):
        from app.api.routes import stream_chunks

        second_url_requested = asyncio.Event()

        async def get_download_url(file_id):
            if file_id == "first":
                return "https://example/first"
            second_url_requested.set()
            return "https://example/second"

        class StreamResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def aiter_bytes(self):
                await second_url_requested.wait()
                yield b"chunk"

        service = SimpleNamespace(get_download_url=AsyncMock(side_effect=get_download_url))
        client = SimpleNamespace(stream=lambda *args, **kwargs: StreamResponse())

        chunks = []
        async for chunk in stream_chunks(["1:first", "2:second"], service, client):
            chunks.append(chunk)
            break

        self.assertTrue(second_url_requested.is_set())
        self.assertEqual(chunks, [b"chunk"])

    async def test_should_increase_reconcile_delay_for_large_file_sets(self):
        settings = SimpleNamespace(TELEGRAM_RECONCILE_INTERVAL=60)
        service = TelegramSyncService(settings)

        self.assertEqual(service._get_reconcile_interval(500), 60)
        self.assertEqual(service._get_reconcile_interval(5_000), 300)
        self.assertEqual(service._get_reconcile_interval(20_000), 900)


if __name__ == "__main__":
    unittest.main()
