from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import SESSION_COOKIE, DbDep, UserDep
from folio.api.errors import ApiError
from folio.api.middleware import is_https
from folio.db.models import User
from folio.security import ratelimit
from folio.security.passwords import hash_password, needs_rehash, verify_password
from folio.security.sessions import REMEMBER_TTL, create_session, end_session
from folio.security.users import normalize_username

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False


class MeOut(BaseModel):
    username: str


def issue_session(
    request: Request, response: Response, db: Session, user: User, remember: bool
) -> None:
    token, _ = create_session(db, user, remember)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(REMEMBER_TTL.total_seconds()) if remember else None,
        httponly=True,
        samesite="strict",
        secure=is_https(request),
        path="/",
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: DbDep) -> MeOut:
    ip = request.client.host if request.client else "unknown"
    username = normalize_username(body.username)

    wait = ratelimit.retry_after(db, ip, username)
    if wait is not None:
        raise ApiError(
            429,
            "Too many login attempts",
            f"Try again in {max(1, wait // 60)} minute(s).",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.username == username))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        ratelimit.record_failure(db, ip, username)
        db.commit()  # the failure must persist even though this request errors
        raise ApiError(401, "Wrong username or password", "Check your credentials and try again.")

    ratelimit.clear(db, ip, username)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    issue_session(request, response, db, user, body.remember)
    return MeOut(username=user.username)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DbDep) -> None:
    end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeOut)
def me(user: UserDep) -> MeOut:
    return MeOut(username=user.username)
