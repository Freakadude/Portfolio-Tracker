from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from folio.api.errors import problem
from folio.db.migrate import is_at_head

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving."""
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
def readyz(request: Request) -> JSONResponse | dict[str, str]:
    """Readiness: the database answers and its schema is at the latest migration."""
    engine = request.app.state.engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        if not is_at_head(engine):
            return problem(503, "Not ready", "Database migrations have not been applied.")
    except Exception:
        return problem(503, "Not ready", "The database is not reachable.")
    return {"status": "ready"}
