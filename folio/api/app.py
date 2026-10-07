from collections.abc import Callable
from pathlib import Path

import httpx
import httpx2
from fastapi import FastAPI

from folio import restore as restore_module
from folio.api.errors import install_error_handlers
from folio.api.middleware import CsrfMiddleware, RequestLogMiddleware, SecurityHeadersMiddleware
from folio.api.routers import (
    accounts,
    agent,
    alerts,
    analytics,
    assistant,
    auth,
    backups,
    calendar,
    corporate_actions,
    dashboards,
    events,
    export,
    health,
    holdings,
    imports,
    instruments,
    macro,
    news,
    notifications,
    portfolio,
    positions,
    recommendations,
    reports,
    schedules,
    sleeves,
    strategies,
    strategy_review,
    system,
    transactions,
    watchlists,
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
    llm_transport: httpx2.BaseTransport | None = None,
    restart: Callable[[], None] | None = None,
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
    app.state.llm_transport = llm_transport  # tests replay recorded Anthropic responses
    # what a restore calls once the response is out: stop the process so the container restarts
    app.state.restart = restart or restore_module.exit_soon

    install_error_handlers(app)
    # Added last runs first: security headers wrap everything, including CSRF rejections.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLogMiddleware)

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(assistant.router, prefix=API_PREFIX)
    app.include_router(setup_router.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)
    app.include_router(schedules.router, prefix=API_PREFIX)
    app.include_router(accounts.router, prefix=API_PREFIX)
    app.include_router(instruments.router, prefix=API_PREFIX)
    app.include_router(holdings.router, prefix=API_PREFIX)
    app.include_router(transactions.router, prefix=API_PREFIX)
    app.include_router(positions.router, prefix=API_PREFIX)
    app.include_router(portfolio.router, prefix=API_PREFIX)
    app.include_router(analytics.router, prefix=API_PREFIX)
    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(backups.router, prefix=API_PREFIX)
    app.include_router(imports.router, prefix=API_PREFIX)
    app.include_router(corporate_actions.router, prefix=API_PREFIX)
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(export.router, prefix=API_PREFIX)
    app.include_router(dashboards.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(sleeves.router, prefix=API_PREFIX)
    app.include_router(watchlists.router, prefix=API_PREFIX)
    app.include_router(strategies.router, prefix=API_PREFIX)
    app.include_router(strategy_review.router, prefix=API_PREFIX)
    app.include_router(macro.router, prefix=API_PREFIX)
    app.include_router(news.router, prefix=API_PREFIX)
    app.include_router(calendar.router, prefix=API_PREFIX)
    app.include_router(notifications.router, prefix=API_PREFIX)
    app.include_router(alerts.router, prefix=API_PREFIX)
    app.include_router(agent.router, prefix=API_PREFIX)
    app.include_router(recommendations.router, prefix=API_PREFIX)
    app.include_router(health.router)
    mount_spa(app, static_dir or STATIC_DIR)  # last: its catch-all route must not shadow the API
    return app
