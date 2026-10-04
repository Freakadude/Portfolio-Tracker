from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from folio.db.engine import ensure_sqlite_dir

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str) -> None:
    ensure_sqlite_dir(url)
    command.upgrade(_config(url), "head")


def is_at_head(engine: Engine) -> bool:
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current == script.get_current_head()
