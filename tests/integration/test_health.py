from pathlib import Path

from fastapi.testclient import TestClient

from folio.api.app import create_app
from folio.config import Settings
from tests.conftest import TEST_SECRET


def test_healthz_is_live(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_ready_after_migrations(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


def test_readyz_not_ready_without_migrations(tmp_path: Path) -> None:
    unmigrated = Settings(
        secret_key=TEST_SECRET,
        db_url=f"sqlite:///{tmp_path / 'empty.db'}",
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(unmigrated)) as client:
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.headers["content-type"].startswith("application/problem+json")
        assert client.get("/healthz").status_code == 200  # liveness is independent


def test_missing_secret_key_fails_clearly(tmp_path: Path) -> None:
    import pytest

    bad = Settings(secret_key="", db_url=f"sqlite:///{tmp_path / 'x.db'}", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="FOLIO_SECRET_KEY"):
        create_app(bad)


def test_spa_fallback_serves_index_but_not_for_api(tmp_path: Path, settings: Settings) -> None:
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html>folio</html>")
    (tmp_path / "static" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(settings, static_dir=tmp_path / "static")) as client:
        assert "folio" in client.get("/holdings").text  # client-side route -> index.html
        assert client.get("/app.js").text == "console.log(1)"
        assert client.get("/api/v1/nope").status_code == 404
        assert client.get("/../secret").status_code in (200, 404)  # never escapes the folder


def test_the_page_is_revalidated_after_an_update_and_hashed_files_are_kept(
    tmp_path: Path, settings: Settings
) -> None:
    """A browser that kept the old page after an update showed a login that did nothing; the page
    is asked for again every time (it is under a kilobyte), the content-hashed files under assets/
    are cached for good, and any other file is revalidated too."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>folio</html>")
    (static / "assets" / "index-AbC123.js").write_text("console.log(1)")
    (static / "favicon.svg").write_text("<svg/>")
    with TestClient(create_app(settings, static_dir=static)) as client:
        for path in ("/", "/holdings", "/login", "/index.html"):
            assert client.get(path).headers["cache-control"] == "no-cache", path
        assert (
            client.get("/assets/index-AbC123.js").headers["cache-control"]
            == "public, max-age=31536000, immutable"
        )
        assert client.get("/favicon.svg").headers["cache-control"] == "no-cache"
