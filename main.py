"""Combined app: Core A (tenant_core) + Core B (gateway_core) in one process.

Run with ONE worker:  uvicorn main:app --host 0.0.0.0 --port 8001
The live connection lists are in memory (common/hubs.py). To run the cores as separate
services later, swap those hubs for Redis pub/sub.
"""
import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete
import sys
from common import models  # noqa: F401
from common.config import get_settings
from common.database import SessionLocal
from common.models import RevokedToken, utcnow
from gateway_core.routers import webhook as gateway_webhook
from gateway_core.routers import ws as gateway_ws
from tenant_core.routers import actions, admin, admin_telephony, auth, logs, numbers
from tenant_core.routers import ws as tenant_ws

WEB = Path(__file__).parent / "web"
sys.path.append(str(Path(__file__).resolve().parent))

PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
        "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'"
    ),
}


def purge_expired_tokens() -> None:
    with SessionLocal() as db:
        db.execute(delete(RevokedToken).where(RevokedToken.expires_at < utcnow()))
        db.commit()


async def _purge_loop() -> None:
    while True:
        await asyncio.to_thread(purge_expired_tokens)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Tables come from Alembic: run `alembic upgrade head` before starting.
    task = asyncio.create_task(_purge_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


_production = get_settings().app_env.lower() == "production"
app = FastAPI(
    title="Dialer",
    lifespan=lifespan,
    docs_url=None if _production else "/docs",
    redoc_url=None,
    openapi_url=None if _production else "/openapi.json",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# Core A: tenants
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_telephony.router)
app.include_router(numbers.router)
app.include_router(logs.router)
app.include_router(actions.router)
app.include_router(tenant_ws.router)
# Core B: phones
app.include_router(gateway_webhook.router)
app.include_router(gateway_ws.router)

app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(WEB / name, headers=PAGE_HEADERS)


@app.get("/", include_in_schema=False)
def login_page():
    return _page("login.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return _page("dashboard.html")


@app.get("/panel", include_in_schema=False)
def admin_page():
    return _page("admin.html")


@app.get("/reset-password", include_in_schema=False)
def reset_page():
    return _page("reset.html")


@app.get("/health")
def health():
    return {"status": "ok"}
