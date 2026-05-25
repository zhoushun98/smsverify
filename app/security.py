from __future__ import annotations

import secrets

from fastapi import Request
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.responses import Response


COOKIE_NAME = "smsverify_admin"


class SessionManager:
    def __init__(self, secret_key: str):
        self.serializer = URLSafeSerializer(secret_key, salt="admin-session")

    def get_username(self, request: Request) -> str | None:
        raw = request.cookies.get(COOKIE_NAME)
        if not raw:
            return None
        try:
            data = self.serializer.loads(raw)
        except BadSignature:
            return None
        username = data.get("username") if isinstance(data, dict) else None
        return username if isinstance(username, str) else None

    def login(self, response: Response, *, username: str) -> None:
        response.set_cookie(
            COOKIE_NAME,
            self.serializer.dumps({"username": username}),
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 12,
        )

    def logout(self, response: Response) -> None:
        response.delete_cookie(COOKIE_NAME)


def credentials_match(
    *,
    expected_username: str,
    expected_password: str,
    username: str,
    password: str,
) -> bool:
    if not expected_password:
        return False
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(
        password,
        expected_password,
    )
