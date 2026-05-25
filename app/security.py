from __future__ import annotations

import hashlib
import secrets

from fastapi import Request
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.responses import Response


COOKIE_NAME = "smsverify_admin"
ORDER_ACCESS_COOKIE_NAME = "smsverify_order_access"


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


class OrderAccessManager:
    def __init__(self, secret_key: str, *, max_orders: int = 20):
        self.serializer = URLSafeSerializer(secret_key, salt="order-access")
        self.max_orders = max_orders

    def has_access(self, request: Request, *, public_token: str) -> bool:
        return self._digest(public_token) in self._load(request)

    def grant(self, response: Response, request: Request, *, public_token: str) -> None:
        token_digest = self._digest(public_token)
        existing = [entry for entry in self._load(request) if entry != token_digest]
        existing.append(token_digest)
        response.set_cookie(
            ORDER_ACCESS_COOKIE_NAME,
            self.serializer.dumps({"orders": existing[-self.max_orders :]}),
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 24,
        )

    def _load(self, request: Request) -> list[str]:
        raw = request.cookies.get(ORDER_ACCESS_COOKIE_NAME)
        if not raw:
            return []
        try:
            data = self.serializer.loads(raw)
        except BadSignature:
            return []
        orders = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(orders, list):
            return []
        return [entry for entry in orders if isinstance(entry, str)]

    @staticmethod
    def _digest(public_token: str) -> str:
        return hashlib.sha256(public_token.encode("utf-8")).hexdigest()


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
