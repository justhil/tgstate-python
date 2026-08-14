import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core import http_client


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_start_web_app_when_telegram_connection_times_out(self):
        app = MagicMock()
        app.state = MagicMock()
        bot_app = MagicMock()
        bot_app.initialize = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        bot_app.shutdown = AsyncMock()
        shared_client = AsyncMock()
        sync_service = MagicMock()
        sync_service.start = AsyncMock(return_value=False)
        sync_service.stop = AsyncMock()

        with (
            patch("app.core.http_client.database.init_db"),
            patch("app.core.http_client.httpx.AsyncClient", return_value=shared_client),
            patch("app.core.http_client.create_bot_app", return_value=bot_app),
            patch(
                "app.core.http_client.get_telegram_sync_service",
                return_value=sync_service,
            ),
        ):
            context = http_client.lifespan(app)
            await context.__aenter__()
            try:
                self.assertIsNone(app.state.bot_app)
                bot_app.shutdown.assert_not_awaited()
            finally:
                await context.__aexit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
