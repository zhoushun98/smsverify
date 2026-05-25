from dataclasses import dataclass

import pytest

from app.db import create_connection, initialize_database
from app.repositories import CdkRepository, OrderRepository
from app.services.redeem import RedeemService


@dataclass
class FakeSmsClient:
    should_fail: bool = False

    def get_number(self, *, country, project, number=None, wait_seconds=30):
        if self.should_fail:
            raise RuntimeError("平台下单失败")
        return {"order_id": "8801", "phone": "855386123456"}

    def get_sms(self, *, order_id):
        return {"status": "received", "sms_code": "123456"}


class BrokenPayloadSmsClient(FakeSmsClient):
    def get_number(self, *, country, project, number=None, wait_seconds=30):
        return {"status": "ok"}


@pytest.fixture()
def connection():
    conn = create_connection(":memory:")
    initialize_database(conn)
    yield conn
    conn.close()


def test_confirm_redeem_consumes_cdk_and_creates_waiting_order(connection):
    cdk_repo = CdkRepository(connection)
    order_repo = OrderRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="兑换")
    service = RedeemService(
        connection=connection,
        cdk_repo=cdk_repo,
        order_repo=order_repo,
        sms_client=FakeSmsClient(),
        country="kh",
        project="chatgpt",
        get_wait=30,
        poll_timeout=300,
    )

    order = service.confirm_redeem(code)

    assert order["platform_order_id"] == "8801"
    assert order["phone"] == "855386123456"
    assert order["status"] == "waiting_sms"
    assert cdk_repo.get_available_by_code(code) is None


def test_confirm_redeem_releases_cdk_when_platform_order_fails(connection):
    cdk_repo = CdkRepository(connection)
    order_repo = OrderRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="失败释放")
    service = RedeemService(
        connection=connection,
        cdk_repo=cdk_repo,
        order_repo=order_repo,
        sms_client=FakeSmsClient(should_fail=True),
        country="kh",
        project="chatgpt",
        get_wait=30,
        poll_timeout=300,
    )

    with pytest.raises(RuntimeError, match="平台下单失败"):
        service.confirm_redeem(code)

    assert cdk_repo.get_available_by_code(code) is not None


def test_confirm_redeem_releases_cdk_when_platform_payload_is_invalid(connection):
    cdk_repo = CdkRepository(connection)
    order_repo = OrderRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="格式错误")
    service = RedeemService(
        connection=connection,
        cdk_repo=cdk_repo,
        order_repo=order_repo,
        sms_client=BrokenPayloadSmsClient(),
        country="kh",
        project="chatgpt",
        get_wait=30,
        poll_timeout=300,
    )

    with pytest.raises(RuntimeError, match="平台下单返回格式不正确"):
        service.confirm_redeem(code)

    assert cdk_repo.get_available_by_code(code) is not None
