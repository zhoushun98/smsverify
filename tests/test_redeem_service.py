from dataclasses import dataclass

import pytest

from app.db import create_connection, initialize_database
from app.repositories import CdkRepository, NumberAllocatorRepository, OrderRepository
from app.services.redeem import RedeemService


@dataclass
class FakeSmsClient:
    should_fail: bool = False
    requests: list[dict] | None = None

    def get_number(self, *, country, project, number=None, wait_seconds=30):
        if self.requests is not None:
            self.requests.append(
                {
                    "country": country,
                    "project": project,
                    "number": number,
                    "wait_seconds": wait_seconds,
                }
            )
        if self.should_fail:
            raise RuntimeError("平台下单失败")
        return {"order_id": f"880{len(self.requests or [])}", "phone": number or "random"}

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


def make_service(
    connection,
    sms_client,
    *,
    number_prefixes: list[str] | None = None,
):
    return RedeemService(
        connection=connection,
        cdk_repo=CdkRepository(connection),
        order_repo=OrderRepository(connection),
        number_allocator_repo=NumberAllocatorRepository(connection),
        sms_client=sms_client,
        country="kh",
        project="chatgpt",
        get_wait=30,
        poll_timeout=300,
        number_prefixes=number_prefixes if number_prefixes is not None else ["855386"],
    )


def test_confirm_redeem_consumes_cdk_and_creates_waiting_order(connection):
    cdk_repo = CdkRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="兑换")
    service = make_service(connection, FakeSmsClient())

    order = service.confirm_redeem(code)

    assert order["platform_order_id"] == "8800"
    assert order["phone"] == "855386000001"
    assert order["status"] == "waiting_sms"
    assert order["requested_number"] == "855386000001"
    assert cdk_repo.get_available_by_code(code) is None


def test_confirm_redeem_sends_system_allocated_numbers_in_rotation(connection):
    cdk_repo = CdkRepository(connection)
    codes = cdk_repo.generate_batch(count=3, batch_name="系统号段")
    requests: list[dict] = []
    service = make_service(
        connection,
        FakeSmsClient(requests=requests),
        number_prefixes=["855386", "855387"],
    )

    for code in codes:
        service.confirm_redeem(code)

    assert [request["number"] for request in requests] == [
        "855386000001",
        "855387000001",
        "855386000002",
    ]


def test_confirm_redeem_requires_system_number_prefixes(connection):
    cdk_repo = CdkRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="缺少号段")
    requests: list[dict] = []
    service = make_service(
        connection,
        FakeSmsClient(requests=requests),
        number_prefixes=[],
    )

    with pytest.raises(RuntimeError, match="未配置可用号段"):
        service.confirm_redeem(code)

    assert requests == []
    assert cdk_repo.get_available_by_code(code) is not None


def test_confirm_redeem_releases_cdk_when_platform_order_fails(connection):
    cdk_repo = CdkRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="失败释放")
    service = make_service(connection, FakeSmsClient(should_fail=True))

    with pytest.raises(RuntimeError, match="平台下单失败"):
        service.confirm_redeem(code)

    assert cdk_repo.get_available_by_code(code) is not None


def test_confirm_redeem_releases_cdk_when_platform_payload_is_invalid(connection):
    cdk_repo = CdkRepository(connection)
    [code] = cdk_repo.generate_batch(count=1, batch_name="格式错误")
    service = make_service(connection, BrokenPayloadSmsClient())

    with pytest.raises(RuntimeError, match="平台下单返回格式不正确"):
        service.confirm_redeem(code)

    assert cdk_repo.get_available_by_code(code) is not None
