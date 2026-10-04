from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.db.models import User
from folio.security.passwords import hash_password

MIN_PASSWORD_LENGTH = 12


def normalize_username(username: str) -> str:
    return username.strip().lower()


def create_user(db: Session, username: str, password: str) -> User:
    name = normalize_username(username)
    if not name:
        raise ValueError("Username must not be empty.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if db.scalar(select(User).where(User.username == name)) is not None:
        raise ValueError("That username already exists.")
    user = User(username=name, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user
