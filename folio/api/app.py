from fastapi import FastAPI

from folio.api.errors import install_error_handlers
from folio.api.middleware import CsrfMiddleware, SecurityHeadersMiddleware
from folio.api.routers import auth
from folio.config import Settings, get_settings
from folio.db.engine import make_engine, make_session_factory

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.require_secret_key()

    app = FastAPI(
        title="Folio",
        docs_url="/api/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    engine = make_engine(settings.db_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    install_error_handlers(app)
    # Added last runs first: security headers wrap everything, including CSRF rejections.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(auth.router, prefix=API_PREFIX)
    return app
