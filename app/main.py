from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.db import create_connection, initialize_database
from app.repositories import CdkRepository, OrderRepository, normalize_cdk
from app.security import SessionManager, credentials_match
from app.services.redeem import InvalidCdkError, OrderNotFoundError, RedeemService
from app.services.smsverify import SmsverifyClient


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
PUBLIC_ORDER_ERROR = "服务暂时不可用，请稍后再试"
PUBLIC_POLL_ERROR = "验证码暂时无法查询，请稍后刷新"
PUBLIC_BALANCE_ERROR = "余额查询失败，请检查服务配置或稍后重试。"


class MissingSmsClient:
    def _raise(self):
        raise RuntimeError("缺少 SMSVERIFY_TOKEN")

    def balance(self):
        self._raise()

    def get_number(self, **kwargs):
        self._raise()

    def get_sms(self, **kwargs):
        self._raise()

    def order_detail(self, **kwargs):
        self._raise()


def create_app(
    *,
    database_path: str | None = None,
    sms_client=None,
    admin_username: str | None = None,
    admin_password: str | None = None,
    session_secret: str | None = None,
) -> FastAPI:
    settings = Settings.from_env()
    resolved_database = database_path or settings.database_path
    connection = create_connection(resolved_database)
    initialize_database(connection)

    resolved_sms_client = sms_client
    if resolved_sms_client is None:
        if settings.smsverify_token:
            resolved_sms_client = SmsverifyClient(
                token=settings.smsverify_token,
                base_url=settings.smsverify_base_url,
            )
        else:
            resolved_sms_client = MissingSmsClient()
    resolved_admin_username = admin_username or settings.admin_username
    resolved_admin_password = admin_password if admin_password is not None else settings.admin_password
    resolved_session_secret = session_secret or settings.session_secret

    app = FastAPI(title="CDK 接码兑换")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    cdk_repo = CdkRepository(connection)
    order_repo = OrderRepository(connection)
    redeem_service = RedeemService(
        connection=connection,
        cdk_repo=cdk_repo,
        order_repo=order_repo,
        sms_client=resolved_sms_client,
        country=settings.country,
        project=settings.project,
        get_wait=settings.get_wait,
        poll_timeout=settings.poll_timeout,
    )
    sessions = SessionManager(resolved_session_secret)

    app.state.connection = connection

    def render(template_name: str, request: Request, status_code: int = 200, **context):
        base_context = {
            "request": request,
            "country": settings.country,
            "project": settings.project,
            "poll_interval": settings.poll_interval,
        }
        base_context.update(context)
        return templates.TemplateResponse(
            request,
            template_name,
            base_context,
            status_code=status_code,
        )

    def require_admin(request: Request):
        username = sessions.get_username(request)
        if username != resolved_admin_username:
            return None
        return username

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render("redeem/index.html", request)

    @app.post("/redeem/check", response_class=HTMLResponse)
    def redeem_check(request: Request, code: str = Form(...)):
        normalized = normalize_cdk(code)
        cdk = cdk_repo.get_available_by_code(normalized)
        if cdk is None:
            return render(
                "redeem/index.html",
                request,
                status_code=400,
                error="CDK 不存在、已使用或已作废",
                code=normalized,
            )
        return render("redeem/check.html", request, code=normalized)

    @app.post("/redeem/confirm")
    def redeem_confirm(request: Request, code: str = Form(...)):
        normalized = normalize_cdk(code)
        try:
            order = redeem_service.confirm_redeem(normalized)
        except InvalidCdkError as exc:
            return render(
                "redeem/index.html",
                request,
                status_code=400,
                error=str(exc),
                code=normalized,
            )
        except Exception as exc:
            return render(
                "redeem/index.html",
                request,
                status_code=502,
                error=PUBLIC_ORDER_ERROR,
                code=normalized,
            )
        return RedirectResponse(f"/orders/{order['id']}", status_code=303)

    @app.get("/orders/{order_id}", response_class=HTMLResponse)
    def order_page(request: Request, order_id: int):
        order = order_repo.get(order_id)
        if order is None:
            return render("redeem/not_found.html", request, status_code=404)
        return render("redeem/order.html", request, order=order)

    @app.get("/orders/{order_id}/poll", response_class=HTMLResponse)
    def order_poll(request: Request, order_id: int):
        try:
            order = redeem_service.poll_sms(order_id)
        except OrderNotFoundError:
            return render("redeem/_order_status.html", request, status_code=404, order=None)
        except Exception:
            order = order_repo.get(order_id)
            return render(
                "redeem/_order_status.html",
                request,
                order=order,
                transient_error=PUBLIC_POLL_ERROR,
            )
        return render("redeem/_order_status.html", request, order=order)

    @app.get("/admin/login", response_class=HTMLResponse)
    def admin_login_page(request: Request):
        return render("admin/login.html", request)

    @app.post("/admin/login")
    def admin_login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        if not credentials_match(
            expected_username=resolved_admin_username,
            expected_password=resolved_admin_password,
            username=username,
            password=password,
        ):
            return render(
                "admin/login.html",
                request,
                status_code=401,
                error="账号或密码错误",
                username=username,
            )
        response = RedirectResponse("/admin", status_code=303)
        sessions.login(response, username=username)
        return response

    @app.post("/admin/logout")
    def admin_logout():
        response = RedirectResponse("/admin/login", status_code=303)
        sessions.logout(response)
        return response

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request):
        if not require_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        try:
            balance = resolved_sms_client.balance()
            balance_error = None
        except Exception as exc:
            balance = None
            balance_error = PUBLIC_BALANCE_ERROR
        return render(
            "admin/index.html",
            request,
            admin_view=True,
            cdk_counts=cdk_repo.count_by_status(),
            order_counts=order_repo.count_by_status(),
            recent_cdks=cdk_repo.list_recent(limit=20),
            balance=balance,
            balance_error=balance_error,
        )

    @app.post("/admin/cdks/generate")
    def admin_generate_cdks(
        request: Request,
        count: int = Form(...),
        batch_name: str = Form(""),
    ):
        if not require_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        cdk_repo.generate_batch(count=count, batch_name=batch_name)
        return RedirectResponse("/admin", status_code=303)

    @app.get("/admin/cdks/export")
    def admin_export_cdks(request: Request):
        if not require_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        body = "\n".join(cdk_repo.export_available_codes())
        if body:
            body += "\n"
        return PlainTextResponse(
            body,
            headers={"Content-Disposition": "attachment; filename=available-cdks.txt"},
        )

    @app.post("/admin/cdks/{cdk_id}/revoke")
    def admin_revoke_cdk(request: Request, cdk_id: int):
        if not require_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        cdk_repo.revoke(cdk_id)
        return RedirectResponse("/admin", status_code=303)

    @app.get("/admin/orders", response_class=HTMLResponse)
    def admin_orders(request: Request):
        if not require_admin(request):
            return RedirectResponse("/admin/login", status_code=303)
        return render(
            "admin/orders.html",
            request,
            admin_view=True,
            orders=order_repo.list_recent(limit=100),
            order_counts=order_repo.count_by_status(),
        )

    return app


app = create_app()
