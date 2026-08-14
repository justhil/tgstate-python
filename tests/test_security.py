import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import PasswordRequest, _ensure_request_authorized
from app.pages import _check_login_rate_limit, _clear_login_attempts


def make_request(
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    if cookies:
        cookie_value = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_value.encode()))

    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/set-password",
        "headers": raw_headers,
    })


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        _clear_login_attempts("test-client")

    def test_should_rate_limit_repeated_failed_logins(self):
        for _ in range(4):
            _check_login_rate_limit("test-client")

        with self.assertRaises(HTTPException) as raised:
            _check_login_rate_limit("test-client")

        self.assertEqual(raised.exception.status_code, 429)

    def test_should_allow_request_with_valid_session_cookie(self):
        settings = SimpleNamespace(PICGO_API_KEY=None)
        request = make_request(cookies={"password": "secret"})

        with patch("app.api.routes.get_active_password", return_value="secret"):
            _ensure_request_authorized(request, settings)

    def test_should_allow_request_with_valid_api_key(self):
        settings = SimpleNamespace(PICGO_API_KEY="secret")
        request = make_request()

        with patch("app.api.routes.get_active_password", return_value=None):
            _ensure_request_authorized(request, settings, "secret")

    def test_should_reject_spoofed_web_request_when_api_key_missing(self):
        settings = SimpleNamespace(PICGO_API_KEY="secret")
        request = make_request(headers={"referer": "https://attacker.example/"})

        with patch("app.api.routes.get_active_password", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                _ensure_request_authorized(request, settings)

        self.assertEqual(raised.exception.status_code, 401)

    async def test_should_reject_password_change_when_request_is_unauthorized(self):
        settings = SimpleNamespace(PICGO_API_KEY="secret")
        request = make_request()

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.api.routes.get_active_password",
            return_value="old-password",
        ):
            previous_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                from app.api.routes import set_password

                with self.assertRaises(HTTPException) as raised:
                    await set_password(
                        PasswordRequest(password="new-password"),
                        request,
                        settings,
                        None,
                    )
            finally:
                os.chdir(previous_dir)

            self.assertEqual(raised.exception.status_code, 401)
            self.assertFalse(Path(temp_dir, ".password").exists())

    async def test_should_allow_password_change_with_valid_current_password(self):
        settings = SimpleNamespace(PICGO_API_KEY=None)
        request = make_request()

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.api.routes.get_active_password",
            return_value="old-password",
        ):
            previous_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                from app.api.routes import set_password

                response = await set_password(
                    PasswordRequest(
                        password="new-password",
                        current_password="old-password",
                    ),
                    request,
                    settings,
                    None,
                )
            finally:
                os.chdir(previous_dir)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(Path(temp_dir, ".password").read_text(encoding="utf-8"), "new-password")

    async def test_should_allow_password_change_with_valid_api_key(self):
        settings = SimpleNamespace(PICGO_API_KEY="secret")
        request = make_request(headers={"x-api-key": "secret"})

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.api.routes.get_active_password",
            return_value="old-password",
        ):
            previous_dir = os.getcwd()
            os.chdir(temp_dir)
            try:
                from app.api.routes import set_password

                response = await set_password(
                    PasswordRequest(password="  new-password  "),
                    request,
                    settings,
                    "secret",
                )
            finally:
                os.chdir(previous_dir)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(Path(temp_dir, ".password").read_text(encoding="utf-8"), "new-password")


if __name__ == "__main__":
    unittest.main()
