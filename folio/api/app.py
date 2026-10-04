from pathlib import Path

import httpx
from fastapi import FastAPI

from folio.api.errors import install_error_handlers
from folio.api.middleware import CsrfMiddleware, RequestLogMiddleware, SecurityHeadersMiddleware
from folio.api.routers import (
    accounts,
    auth,
    corporate_actions,
    health,
    imports,
    instruments,
    positions,
    transactions,
)
from folio.api.routers import settings as settings_router
from folio.api.routers import setup as setup_router
from folio.api.spa import STATIC_DIR, mount_spa
from folio.config import Settings, get_settings
from folio.db.engine import make_engine, make_session_factory
from folio.marketdata.runtime import make_usage_tracker

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    static_dir: Path | None = None,
    provider_transport: httpx.BaseTransport | None = None,
    provider_http_options: dict[str, object] | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    cfg.require_secret_key()

    app = FastAPI(
        title="Folio",
        docs_url="/api/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    engine = make_engine(cfg.db_url)
    app.state.settings = cfg
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    # Interactive lookups (resolving an ISIN) run in the web process; the call budget lives in
    # the database, so both processes share it (ADR 0008). Tests inject a scripted transport.
    app.state.usage = make_usage_tracker(app.state.session_factory)
    app.state.breakers = {}
    app.state.provider_transport = provider_transport
    app.state.provider_http_options = provider_http_options or {}

    install_error_handlers(app)
    # Added last runs first: security headers wrap everything, including CSRF rejections.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLogMiddleware)

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(setup_router.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)
    app.include_router(accounts.router, prefix=API_PREFIX)
    app.include_router(instruments.router, prefix=API_PREFIX)
    app.include_router(transactions.router, prefix=API_PREFIX)
    app.include_router(positions.router, prefix=API_PREFIX)
    app.include_router(imports.router, prefix=API_PREFIX)
    app.include_router(corporate_actions.router, prefix=API_PREFIX)
    app.include_router(health.router)
    mount_spa(app, static_dir or STATIC_DIR)  # last: its catch-all route must not shadow the API
    return app
