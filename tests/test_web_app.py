from fastapi.testclient import TestClient

from app.main import create_app


class FakeSmsClient:
    def __init__(self):
        self.requests: list[dict] = []

    def balance(self):
        return {
            "available_balance": "10.00",
            "reserved_balance": "0.00",
            "currency": "USD",
        }

    def get_number(self, *, country, project, number=None, wait_seconds=30):
        self.requests.append(
            {
                "country": country,
                "project": project,
                "number": number,
                "wait_seconds": wait_seconds,
            }
        )
        return {"order_id": "9901", "phone": number}

    def get_sms(self, *, order_id):
        return {"status": "received", "sms_code": "654321"}

    def order_detail(self, *, order_id):
        return {"status": "received"}


class SensitiveFailureSmsClient(FakeSmsClient):
    def get_number(self, *, country, project, number=None, wait_seconds=30):
        raise RuntimeError("https://smsverify.online/api/get_number token=secret")


class SensitivePollFailureSmsClient(FakeSmsClient):
    def get_sms(self, *, order_id):
        raise RuntimeError("https://smsverify.online/api/get_sms token=secret")


def make_test_app(tmp_path, sms_client):
    return create_app(
        database_path=str(tmp_path / "app.db"),
        sms_client=sms_client,
        admin_username="admin",
        admin_password="secret",
        session_secret="test-secret",
        number_prefixes=["855386"],
    )


def test_visitor_can_check_confirm_and_poll_cdk(tmp_path, monkeypatch):
    monkeypatch.setattr("app.repositories.secrets.randbelow", lambda upper_bound: 234567)
    sms_client = FakeSmsClient()
    app = make_test_app(tmp_path, sms_client)
    client = TestClient(app)

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "secret"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    generated = client.post(
        "/admin/cdks/generate",
        data={"count": "1", "batch_name": "网页测试"},
        follow_redirects=False,
    )
    assert generated.status_code == 303

    export = client.get("/admin/cdks/export")
    code = export.text.strip()
    assert code

    check = client.post("/redeem/check", data={"code": code})
    assert check.status_code == 200
    assert "确认兑换" in check.text
    assert "chatgpt" in check.text

    confirm = client.post(
        "/redeem/confirm",
        data={"code": code},
        follow_redirects=False,
    )
    assert confirm.status_code == 303
    order_url = confirm.headers["location"]
    assert sms_client.requests[0]["number"] == "855386334567"

    order_page = client.get(order_url)
    assert "+855386334567" in order_page.text

    poll = client.get(f"{order_url}/poll")
    assert poll.status_code == 200
    assert "654321" in poll.text


def test_public_pages_do_not_expose_admin_entry(tmp_path):
    app = make_test_app(tmp_path, FakeSmsClient())
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "后台" not in response.text
    assert "/admin" not in response.text


def test_visitor_order_page_does_not_expose_platform_order_id(tmp_path):
    app = make_test_app(tmp_path, FakeSmsClient())
    client = TestClient(app)

    client.post("/admin/login", data={"username": "admin", "password": "secret"})
    client.post("/admin/cdks/generate", data={"count": "1", "batch_name": "隐藏平台单号"})
    code = client.get("/admin/cdks/export").text.strip()
    response = client.post(
        "/redeem/confirm",
        data={"code": code},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "平台订单" not in response.text
    assert "9901" not in response.text


def test_visitor_order_failure_is_sanitized(tmp_path):
    app = make_test_app(tmp_path, SensitiveFailureSmsClient())
    client = TestClient(app)

    client.post("/admin/login", data={"username": "admin", "password": "secret"})
    client.post("/admin/cdks/generate", data={"count": "1", "batch_name": "失败脱敏"})
    code = client.get("/admin/cdks/export").text.strip()
    response = client.post("/redeem/confirm", data={"code": code})

    assert response.status_code == 502
    assert "服务暂时不可用，请稍后再试" in response.text
    assert "smsverify" not in response.text.lower()
    assert "https://" not in response.text
    assert "token" not in response.text.lower()


def test_poll_failure_is_sanitized_for_visitor(tmp_path):
    app = make_test_app(tmp_path, SensitivePollFailureSmsClient())
    client = TestClient(app)

    client.post("/admin/login", data={"username": "admin", "password": "secret"})
    client.post("/admin/cdks/generate", data={"count": "1", "batch_name": "轮询脱敏"})
    code = client.get("/admin/cdks/export").text.strip()
    confirm = client.post(
        "/redeem/confirm",
        data={"code": code},
        follow_redirects=False,
    )
    order_url = confirm.headers["location"]
    response = client.get(f"{order_url}/poll")

    assert response.status_code == 200
    assert "验证码暂时无法查询，请稍后刷新" in response.text
    assert "smsverify" not in response.text.lower()
    assert "https://" not in response.text
    assert "token" not in response.text.lower()


def test_admin_login_rejects_wrong_password(tmp_path):
    app = make_test_app(tmp_path, FakeSmsClient())
    client = TestClient(app)

    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401
    assert "账号或密码错误" in response.text
