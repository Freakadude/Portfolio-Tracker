"""Seeds the end-to-end database with what an agent run leaves behind (used by the Playwright
test of the recommendations; never part of the app).

The calculation is made by the app's own `run_calculator` tool on the e2e data, so "accept and
make drafts" re-checks it against the same code. The recommendations and the run row are written
as the agent would have written them. Nothing here calls any LLM or any network.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import select

from folio.agent.facts import FactsBuilder
from folio.agent.runs import finish_run, start_run
from folio.agent.tools import ToolBox
from folio.config import get_settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import Recommendation


def main() -> None:
    settings = get_settings()
    with make_session_factory(make_engine(settings.db_url))() as db:
        if db.scalar(select(Recommendation.id).limit(1)) is not None:
            return  # Playwright restarts its worker after a failure; seed once
        now = dt.datetime.now(dt.UTC)
        box = ToolBox(db, now, True, FactsBuilder())
        result, failed = box.run(
            "run_calculator", {"kind": "allocator", "amount_eur": "500", "sleeve": None}
        )
        if failed:
            raise SystemExit(f"the calculator failed: {result}")
        calc_id = int(str(result["calculation_id"]).removeprefix("calc-"))
        run = start_run(db, "daily", "daily_review", "claude-sonnet-5-5", "system@1+e2e", now)
        run.cost_eur = Decimal("0.0123")
        run.input_tokens, run.output_tokens = 4300, 650
        run.context = {"run": {"type": "daily_review"}}
        run.tool_calls = [
            {"name": "get_signals", "input": {"state": "open"}, "error": False, "result": "{}"},
            {
                "name": "run_calculator",
                "input": {"kind": "allocator"},
                "error": False,
                "result": "{}",
            },
        ]
        run.findings = "E2E Core is under target. Allocator calc: buy units of E2E Stock."
        run.digest = "One sleeve is under its target."
        run.output = {
            "text": "{}",
            "verdicts": [
                {"index": 0, "accepted": True, "reasons": []},
                {"index": 1, "accepted": True, "reasons": []},
                {
                    "index": 2,
                    "accepted": False,
                    "reasons": ["a trade needs a calculation from this run"],
                },
            ],
        }
        finish_run(db, run, now)
        common = {
            "run_id": run.id,
            "sources": [],
            "confidence": "medium",
            "what_would_change_this": "A rally before the order is placed.",
            "expires_at": now + dt.timedelta(days=14),
            "price_at_creation": {},
        }
        db.add(
            Recommendation(
                action_type="direct_contribution",
                severity="medium",
                subjects=["E2E Core"],
                title="Direct new money to E2E Core",
                summary="E2E Core is under its target; the calculator buys units of E2E Stock.",
                rationale="The drift rule fired and the allocator orders the units shown.",
                calculation_id=calc_id,
                evidence=[{"kind": "metric", "ref": "run_calculator", "note": "Allocator result"}],
                status="new",
                **common,
            )
        )
        db.add(
            Recommendation(
                action_type="watch",
                severity="low",
                subjects=["E2E Watched"],
                title="Watch E2E Watched",
                summary="E2E Watched has moved a lot lately.",
                rationale="Its price alert fired earlier this week.",
                evidence=[{"kind": "metric", "ref": "get_signals", "note": "Alert"}],
                status="new",
                **common,
            )
        )
        db.add(
            Recommendation(
                action_type="trim",
                severity="high",
                subjects=["E2E Core"],
                title="Sell E2E Stock now",
                summary="Sell everything.",
                rationale="Made up.",
                evidence=[],
                status="refused",
                refused_reason="a trade needs a calculation from this run",
                **common,
            )
        )
        db.commit()


if __name__ == "__main__":
    main()
