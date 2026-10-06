"""A file to attach when something goes wrong (FR-SY-10).

It says how Folio is set up, what failed lately and what the server logged, and it leaves out
everything private: no API keys or passwords (and anything that looks like one is scrubbed), no
holdings, names of instruments, transactions or amounts. Counts of rows are included, so an empty
database can be told from a broken one.
"""

import platform
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from folio import restore
from folio.config import Settings
from folio.db import migrate
from folio.db.base import utcnow
from folio.db.models import Account, AuditLog
from folio.db.models_insight import AgentRun, NewsSource, Recommendation
from folio.db.models_ledger import (
    Instrument,
    JobRequest,
    JobRun,
    LedgerTransaction,
    PriceBar,
    ProviderCall,
)
from folio.logging import recent_problems
from folio.security.redact import scrub

LOG_CHARS = 600  # a job's log or an error can run long; the start says what happened


def _short(text: str | None) -> str | None:
    if text is None:
        return None
    text = scrub(text)
    return text if len(text) <= LOG_CHARS else text[:LOG_CHARS] + " [cut]"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _count(db: Session, model: Any, *where: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _version() -> str:
    try:
        return package_version("folio")
    except PackageNotFoundError:
        return "not installed as a package"


def build_report(
    db: Session, engine: Engine, settings: Settings, secret_names: set[str]
) -> dict[str, Any]:
    """`secret_names` are the stored secrets that have a value (names only, never the value)."""
    now = utcnow()
    since = now - timedelta(hours=24)
    today = datetime.now(UTC).date()

    runs = db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(40)).all()
    requests = db.scalars(select(JobRequest).order_by(JobRequest.id.desc()).limit(20)).all()
    sources = db.scalars(
        select(NewsSource).where(NewsSource.deleted_at.is_(None), NewsSource.failures > 0)
    ).all()
    agent_failures = db.scalars(
        select(AgentRun).where(AgentRun.status == "failed").order_by(AgentRun.id.desc()).limit(10)
    ).all()
    calls = db.execute(
        select(ProviderCall.provider, ProviderCall.count).where(ProviderCall.day == today)
    ).all()
    last_price = db.scalar(select(func.max(PriceBar.date)))

    return {
        "about": (
            "Folio diagnostics. It contains no API keys, passwords, holdings, instrument names, "
            "transactions or amounts; it is safe to attach to a bug report."
        ),
        "generated_at": now.isoformat(),
        "app": {
            "version": _version(),
            "build": settings.version,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "timezone": settings.tz,
            "log_level": settings.log_level,
        },
        "database": {
            "migration_at_head": migrate.is_at_head(engine),
            "last_restore": restore.last_result(settings.db_url),
            "rows": {
                "accounts": _count(db, Account, Account.deleted_at.is_(None)),
                "instruments": _count(db, Instrument, Instrument.deleted_at.is_(None)),
                "transactions": _count(
                    db, LedgerTransaction, LedgerTransaction.deleted_at.is_(None)
                ),
                "recommendations": _count(db, Recommendation),
                "audit_entries": _count(db, AuditLog),
            },
            "newest_price_day": last_price.isoformat() if last_price is not None else None,
        },
        "configuration": {
            "base_url_set": settings.base_url is not None,
            "tailscale_sign_in": bool(settings.tailscale_user and settings.trusted_proxies),
            "extra_backup_dir_set": settings.extra_backup_dir is not None,
            "secrets_with_a_value": sorted(secret_names),
        },
        "provider_calls_today": {name: int(count) for name, count in calls},
        "failed_jobs_24h": sum(1 for r in runs if r.status == "failed" and r.started_at >= since),
        "recent_job_runs": [
            {
                "id": r.id,
                "job": r.job,
                "status": r.status,
                "started_at": _iso(r.started_at),
                "seconds": (
                    round((r.finished_at - r.started_at).total_seconds(), 2)
                    if r.finished_at is not None
                    else None
                ),
                "log": _short(r.log) if r.status != "ok" else None,
            }
            for r in runs
        ],
        "recent_job_requests": [
            {
                "id": r.id,
                "job": r.job,
                "status": r.status,
                "created_at": _iso(r.created_at),
                "error": _short(r.error),
            }
            for r in requests
        ],
        "news_sources_failing": [
            {
                "name": s.name,
                "kind": s.kind,
                "failures": s.failures,
                "last_fetch_at": _iso(s.last_fetch_at),
                "last_error": _short(s.last_error),
            }
            for s in sources
        ],
        "agent_runs_failed_recently": [
            {"id": r.id, "type": r.run_type, "at": _iso(r.started_at), "error": _short(r.error)}
            for r in agent_failures
        ],
        "recent_warnings_and_errors_from_the_web_server": recent_problems(),
    }
