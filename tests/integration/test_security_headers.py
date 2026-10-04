from fastapi.testclient import TestClient


def test_security_headers_present(client: TestClient) -> None:
    h = client.get("/api/v1/auth/me").headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"


def test_post_without_csrf_header_is_rejected(client: TestClient) -> None:
    del client.headers["X-CSRF-Token"]
    r = client.post("/api/v1/auth/login", json={"username": "a", "password": "b"})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "content-security-policy" in r.headers  # headers also wrap rejections


def test_post_with_wrong_csrf_token_is_rejected(client: TestClient) -> None:
    client.headers["X-CSRF-Token"] = "not-the-cookie-value"
    assert client.post("/api/v1/auth/logout").status_code == 403


def test_csrf_cookie_flags(client: TestClient) -> None:
    from fastapi.testclient import TestClient as TC

    fresh = TC(client.app)
    cookie = fresh.get("/api/v1/auth/me").headers["set-cookie"].lower()
    assert "samesite=strict" in cookie
