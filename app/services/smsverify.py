from __future__ import annotations

from typing import Any

import httpx


class SmsverifyApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SmsverifyClient:
    def __init__(self, *, token: str, base_url: str):
        if not token:
            raise ValueError("缺少 SMSVERIFY_TOKEN")
        if not base_url:
            raise ValueError("缺少 SMSVERIFY_BASE_URL")
        self.token = token
        self.base_url = base_url.rstrip("/")

    def balance(self) -> dict[str, Any]:
        return self._get("/api/balance")

    def get_number(
        self,
        *,
        country: str,
        project: str,
        number: str | None = None,
        wait_seconds: int = 30,
    ) -> dict[str, Any]:
        return self._get(
            "/api/get_number",
            params={
                "country": country,
                "project": project,
                "number": number,
                "wait_seconds": wait_seconds,
            },
        )

    def get_sms(self, *, order_id: str) -> dict[str, Any]:
        return self._get("/api/get_sms", params={"order_id": order_id})

    def order_detail(self, *, order_id: str) -> dict[str, Any]:
        return self._get(f"/api/order/{order_id}")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean_params = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "smsverify-web/1.0",
        }
        try:
            with httpx.Client(base_url=self.base_url, timeout=60) as client:
                response = client.get(path, params=clean_params, headers=headers)
        except httpx.HTTPError as exc:
            raise SmsverifyApiError(f"请求平台失败：{exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise SmsverifyApiError(
                f"平台返回非 JSON 响应：HTTP {response.status_code}",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400:
            raise SmsverifyApiError(
                f"平台请求失败：HTTP {response.status_code} {payload}",
                status_code=response.status_code,
            )
        if not isinstance(payload, dict):
            raise SmsverifyApiError("平台返回格式不正确")
        return payload
