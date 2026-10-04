import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from folio.api.errors import problem

CSRF_COOKIE = "folio_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)
# The interactive API docs load Swagger UI from a CDN.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com; frame-ancestors 'none'"
)


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie: unsafe /api requests must echo the folio_csrf cookie in a header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cookie = request.cookies.get(CSRF_COOKIE)
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api"):
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not hmac.compare_digest(cookie, header):
                return problem(403, "CSRF check failed", "Missing or invalid CSRF token.")
        response = await call_next(request)
        if not cookie:
            response.set_cookie(
                CSRF_COOKIE,
                secrets.token_urlsafe(32),
                samesite="strict",
                secure=is_https(request),
                httponly=False,  # the SPA must read it to echo it
                path="/",
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        docs = request.url.path.startswith(("/api/docs", "/api/redoc"))
        response.headers.setdefault("Content-Security-Policy", DOCS_CSP if docs else CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response
