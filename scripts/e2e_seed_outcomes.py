"""Gives the end-to-end database's recommendations the outcome the daily job would have measured
(used by the Playwright test of the track record; never part of the app).

The recommendations come from `e2e_seed_agent.py`. Nothing here calls the network.
"""

from sqlalchemy import select

from folio.config import get_settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import Recommendation


def main() -> None:
    settings = get_settings()
    with make_session_factory(make_engine(settings.db_url))() as db:
        for rec in db.scalars(select(Recommendation).where(Recommendation.status != "refused")):
            if rec.outcome:
                continue  # seed once
            if rec.action_type == "direct_contribution":
                change, hit = "0.050000", True
            else:
                change, hit = "0.100000", None  # a watch item is measured, never a hit
            rec.outcome = {
                "d30": {
                    "measured_on": "2026-10-01",
                    "subjects": {"E2E Stock": {"start": "100", "end": "105", "return": change}},
                    "return": change,
                    "hit": hit,
                }
            }
        db.commit()


if __name__ == "__main__":
    main()
