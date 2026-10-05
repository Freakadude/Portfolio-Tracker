from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from folio.api.errors import ApiError
from folio.config import Settings
from folio.db.models import User
from folio.security.secrets import SecretStore
from folio.security.sessions import resolve_session

SESSION_COOKIE = "folio_session"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# scope="function": the commit happens when the endpoint returns, before the response is sent.
# With the default (request) scope FastAPI commits after the response has gone out, so a client
# that reads right after a write (sign in, then ask who is signed in) can still miss the write.
DbDep = Annotated[Session, Depends(get_db, scope="function")]


def current_user(request: Request, db: DbDep) -> User:
    user = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise ApiError(401, "Not signed in", "Sign in to continue.")
    # Save the session's "last seen" update now. SQLite allows one writer at a time, and a
    # handler that calls a provider charges the call budget through a separate connection;
    # an open write transaction here would make that charge wait and fail.
    db.commit()
    return user


UserDep = Annotated[User, Depends(current_user)]


def get_secret_store(request: Request, db: DbDep) -> SecretStore:
    return SecretStore(db, request.app.state.settings.require_secret_key())


StoreDep = Annotated[SecretStore, Depends(get_secret_store)]
