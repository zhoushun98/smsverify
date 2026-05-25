from __future__ import annotations

import sqlite3
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.repositories import CdkRepository, NumberAllocatorRepository, OrderRepository


logger = logging.getLogger(__name__)
PUBLIC_ORDER_ERROR = "服务暂时不可用，请稍后再试"


class SmsClient(Protocol):
    def get_number(
        self,
        *,
        country: str,
        project: str,
        number: str | None = None,
        wait_seconds: int = 30,
    ) -> dict: ...

    def get_sms(self, *, order_id: str) -> dict: ...


class InvalidCdkError(ValueError):
    pass


class OrderNotFoundError(ValueError):
    pass


class RedeemService:
    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        cdk_repo: CdkRepository,
        order_repo: OrderRepository,
        number_allocator_repo: NumberAllocatorRepository,
        sms_client: SmsClient,
        country: str,
        project: str,
        get_wait: int,
        poll_timeout: int,
        number_prefixes: list[str],
        number_suffix_width: int = 6,
    ):
        self.connection = connection
        self.cdk_repo = cdk_repo
        self.order_repo = order_repo
        self.number_allocator_repo = number_allocator_repo
        self.sms_client = sms_client
        self.country = country
        self.project = project
        self.get_wait = get_wait
        self.poll_timeout = poll_timeout
        self.number_prefixes = number_prefixes
        self.number_suffix_width = number_suffix_width
        self._lock = threading.Lock()

    def confirm_redeem(self, code: str) -> sqlite3.Row:
        cdk = self.cdk_repo.get_available_by_code(code)
        if cdk is None:
            raise InvalidCdkError("CDK 不存在、已使用或已作废")

        with self._lock:
            expires_at = (self._now() + timedelta(seconds=self.poll_timeout)).isoformat()
            with self.connection:
                requested_number = self.number_allocator_repo.allocate(
                    prefixes=self.number_prefixes,
                    suffix_width=self.number_suffix_width,
                )
                order = self.order_repo.create_pending(
                    cdk_id=cdk["id"],
                    requested_number=requested_number,
                    expires_at=expires_at,
                )
                self.cdk_repo.mark_used(cdk["id"], order_id=order["id"])

        try:
            platform_order = self.sms_client.get_number(
                country=self.country,
                project=self.project,
                number=requested_number,
                wait_seconds=self.get_wait,
            )
            if not isinstance(platform_order, dict):
                raise RuntimeError("平台下单返回格式不正确")
            platform_order_id = str(platform_order["order_id"])
            phone = str(platform_order["phone"])
        except KeyError as exc:
            self.cdk_repo.release(cdk["id"])
            self.order_repo.mark_failed(order["id"], error_message=PUBLIC_ORDER_ERROR)
            raise RuntimeError("平台下单返回格式不正确") from exc
        except Exception as exc:
            logger.exception("平台下单失败")
            self.cdk_repo.release(cdk["id"])
            self.order_repo.mark_failed(order["id"], error_message=PUBLIC_ORDER_ERROR)
            raise

        return self.order_repo.attach_platform_order(
            order["id"],
            platform_order_id=platform_order_id,
            phone=phone,
        )

    def poll_sms(self, order_id: int) -> sqlite3.Row:
        order = self.order_repo.get(order_id)
        if order is None:
            raise OrderNotFoundError("订单不存在")

        if order["status"] in {"completed", "manual_review", "failed"}:
            return order
        if order["status"] != "waiting_sms" or not order["platform_order_id"]:
            return order

        if self._is_expired(order["expires_at"]):
            return self.order_repo.mark_manual_review(
                order_id,
                error_message="验证码等待超时，待人工处理",
            )

        data = self.sms_client.get_sms(order_id=order["platform_order_id"])
        sms_code = data.get("sms_code") if isinstance(data, dict) else None
        if sms_code:
            return self.order_repo.mark_completed(order_id, sms_code=str(sms_code))

        if self._is_expired(order["expires_at"]):
            return self.order_repo.mark_manual_review(
                order_id,
                error_message="验证码等待超时，待人工处理",
            )
        return self.order_repo.get(order_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    def _is_expired(self, expires_at: str) -> bool:
        return datetime.fromisoformat(expires_at) <= self._now()
