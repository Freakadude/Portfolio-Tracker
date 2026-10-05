"""The daily macro job (FR-MD-08): fetches every configured indicator series, plus the ones the
active and shadow strategies name, then lets the rules look at them (FR-ST-03)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from folio.jobs.context import JobContext
from folio.jobs.runner import JobLog, JobResult, run_job
from folio.marketdata.base import ProviderError
from folio.marketdata.macro import MacroService, fetch_series
from folio.settings_schema import MacroSeriesConfig, MacroSettings
from folio.settings_store import load_section
from folio.strategies import service as strategies

HISTORY_YEARS = 5  # enough for a chart and every rule window


def wanted_series(db: Session) -> list[MacroSeriesConfig]:
    """The configured list, then the strategies' own series that are not on it yet."""
    configured = MacroSettings.model_validate(load_section(db, "macro").model_dump()).series
    out = list(configured)
    seen = {(s.source, s.code) for s in out}
    for _strategy, _version, definition in strategies.running(db):
        for name, spec in definition.macro_series.items():
            if (spec.source, spec.code) not in seen:
                seen.add((spec.source, spec.code))
                out.append(MacroSeriesConfig(source=spec.source, code=spec.code, name=name))
    return out


def macro_job(ctx: JobContext, *, then_rules: bool = True) -> JobResult:
    def body(db: Session, log: JobLog) -> None:
        today = ctx.today()
        floor = today - timedelta(days=365 * HISTORY_YEARS)
        service = MacroService(db)
        series = wanted_series(db)
        ecb, fred = ctx.ecb_for(db), ctx.fred_for(db)
        missing_key = []
        for item in series:
            start = service.start_for(item.code, floor)
            try:
                # fetch first and write after: a call charged to the budget uses another
                # connection, which must not find this one holding the write lock
                points = fetch_series(item.source, item.code, start, today, ecb, fred)
            except ProviderError as exc:
                log.error(f"{item.name}: {exc}")
                continue
            if points is None:
                missing_key.append(item.name)
                continue
            row = service.series(item.code, item.name, item.source, unit=item.unit)
            changed = service.store(row, points)
            db.commit()
            log.info(f"{item.name}: {changed} new or changed")
        if missing_key:
            log.info(
                f"Skipped without a FRED API key: {', '.join(missing_key)}. "
                "Add the free key under Settings > Providers."
            )

    result = run_job(ctx, "macro", body)
    if then_rules:  # one failing series must not keep the others from the rules
        from folio.jobs.strategies import rules_job  # noqa: PLC0415 - avoids an import cycle

        rules_job(ctx)
    return result
