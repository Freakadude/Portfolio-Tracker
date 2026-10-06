from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.api.deps import SESSION_COOKIE, DbDep, UserDep
from folio.api.errors import ApiError
from folio.api.middleware import is_https
from folio.audit import write_audit
from folio.db.base import utcnow
from folio.db.models import User
from folio.security import ratelimit, totp, twofactor
from folio.security.passwords import hash_password, needs_rehash, verify_password
from folio.security.sessions import REMEMBER_TTL, create_session, end_session
from folio.security.users import normalize_username

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False
    code: str | None = Field(default=None, max_length=64)  # the second factor, once it is on


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

    if user.totp_enabled:  # the password was right; the second factor is next (FR-SY-03)
        if not body.code or not body.code.strip():
            raise ApiError(
                401,
                "Code needed",
                "Enter the code from your authenticator app, or one of your recovery codes.",
                code="totp_required",
            )
        key = request.app.state.settings.require_secret_key()
        if not twofactor.check_login(db, user, body.code, utcnow(), key):
            ratelimit.record_failure(db, ip, username)  # a wrong code counts like a wrong password
            db.commit()
            raise ApiError(
                401,
                "Wrong code",
                "That code is not right or was already used.",
                code="totp_required",
            )
        write_audit(db, user.username, "user", "sign in with second factor", entity_id=user.id)
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


# --- the second factor (FR-SY-03) ----------------------------------------------------------------


class TotpStatusOut(BaseModel):
    enabled: bool
    pending: bool  # set up but not confirmed with a code yet
    recovery_codes_left: int


class TotpSetupOut(BaseModel):
    secret: str  # to type into the app by hand
    uri: str
    qr_svg: str  # the same link as a QR code


class TotpCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class TotpProveIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=1, max_length=64)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]  # shown this once; only hashes are kept


def _throttled(db: Session, request: Request, user: User) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    wait = ratelimit.retry_after(db, ip, user.username)
    if wait is not None:
        raise ApiError(
            429,
            "Too many attempts",
            f"Try again in {max(1, wait // 60)} minute(s).",
            headers={"Retry-After": str(wait)},
        )
    return ip, user.username


def _status(db: Session, user: User) -> TotpStatusOut:
    s = twofactor.status(db, user)
    return TotpStatusOut(
        enabled=s.enabled, pending=s.pending, recovery_codes_left=s.recovery_codes_left
    )


@router.get("/totp", response_model=TotpStatusOut)
def totp_status(user: UserDep, db: DbDep) -> TotpStatusOut:
    return _status(db, user)


@router.post("/totp/setup", response_model=TotpSetupOut)
def totp_setup(request: Request, user: UserDep, db: DbDep) -> TotpSetupOut:
    """A new secret as a QR code and as text. Nothing changes at sign-in until a code from the
    app is confirmed with POST /auth/totp/enable."""
    key = request.app.state.settings.require_secret_key()
    try:
        secret, uri = twofactor.start_setup(db, user, key)
    except twofactor.TwoFactorError as exc:
        raise ApiError(409, "Already on", str(exc)) from exc
    return TotpSetupOut(secret=totp.group(secret), uri=uri, qr_svg=totp.qr_svg(uri))


@router.post("/totp/enable", response_model=RecoveryCodesOut)
def totp_enable(body: TotpCodeIn, request: Request, user: UserDep, db: DbDep) -> RecoveryCodesOut:
    """Confirm the setup with a code from the app. Returns the recovery codes, once."""
    ip, name = _throttled(db, request, user)
    key = request.app.state.settings.require_secret_key()
    try:
        codes = twofactor.enable(db, user, body.code, utcnow(), key)
    except twofactor.TwoFactorError as exc:
        ratelimit.record_failure(db, ip, name)
        db.commit()
        raise ApiError(422, "Cannot turn it on", str(exc)) from exc
    write_audit(db, user.username, "user", "second factor on", entity_id=user.id)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/totp/disable", status_code=204)
def totp_disable(body: TotpProveIn, request: Request, user: UserDep, db: DbDep) -> None:
    ip, name = _throttled(db, request, user)
    key = request.app.state.settings.require_secret_key()
    try:
        twofactor.disable(db, user, body.password, body.code, utcnow(), key)
    except twofactor.TwoFactorError as exc:
        ratelimit.record_failure(db, ip, name)
        db.commit()
        raise ApiError(422, "Cannot turn it off", str(exc)) from exc
    write_audit(db, user.username, "user", "second factor off", entity_id=user.id)


@router.post("/totp/recovery-codes", response_model=RecoveryCodesOut)
def totp_new_codes(
    body: TotpProveIn, request: Request, user: UserDep, db: DbDep
) -> RecoveryCodesOut:
    """Replace the recovery codes; the old ones stop working."""
    ip, name = _throttled(db, request, user)
    key = request.app.state.settings.require_secret_key()
    try:
        codes = twofactor.new_codes(db, user, body.password, body.code, utcnow(), key)
    except twofactor.TwoFactorError as exc:
        ratelimit.record_failure(db, ip, name)
        db.commit()
        raise ApiError(422, "Cannot make new codes", str(exc)) from exc
    write_audit(db, user.username, "user", "new recovery codes", entity_id=user.id)
    return RecoveryCodesOut(recovery_codes=codes)
