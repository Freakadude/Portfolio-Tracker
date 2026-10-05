"""A write is committed before the client receives the response.

The e2e run on CI caught the failure: signing in returned 200, the page asked who was signed in
straight away, and the session row was not visible yet, because the database dependency committed
after the response had gone out. The page fell back to the login form with no error.
"""

from collections.abc import MutableMapping
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from folio.api.app import create_app
from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import UserSession
from tests.conftest import PASSWORD, USERNAME


def test_the_session_exists_when_the_login_response_starts(settings: Settings, owner: None) -> None:
    app = create_app(settings)
    factory = make_session_factory(make_engine(settings.db_url))
    seen: list[int] = []

    async def watching(scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        async def spy(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start" and scope.get("path", "").endswith(
                "/login"
            ):
                with factory() as other:  # a second connection, like the browser's next request
                    seen.append(other.scalar(select(func.count()).select_from(UserSession)) or 0)
            await send(message)

        await app(scope, receive, spy)

    with TestClient(watching, base_url="http://testserver") as client:
        client.get("/api/v1/auth/me")
        client.headers["X-CSRF-Token"] = client.cookies.get("folio_csrf") or ""
        reply = client.post(
            "/api/v1/auth/login",
            json={"username": USERNAME, "password": PASSWORD, "remember": False},
        )
    assert reply.status_code == 200
    assert seen == [1]  # committed already, not after the response
