"""Seeds the end-to-end database with two stories for the News page test (never part of the app).

One touches a holding (it is assessed, with an outlook and advice); the other was concluded to
touch nothing of the owner's, so the page must not list it. Nothing here calls any LLM or network.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import select

from folio.config import get_settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models_insight import NewsAssessment, NewsCluster, NewsItem, NewsLink, NewsSource
from folio.db.models_ledger import Instrument


def main() -> None:
    settings = get_settings()
    with make_session_factory(make_engine(settings.db_url))() as db:
        if db.scalar(select(NewsCluster.id).where(NewsCluster.title.like("E2E story%"))):
            return  # seed once
        instrument = db.scalars(
            select(Instrument).where(Instrument.deleted_at.is_(None)).order_by(Instrument.id)
        ).first()
        if instrument is None:
            raise SystemExit("the e2e database has no instrument to link a story to")
        now = dt.datetime.now(dt.UTC)
        source = NewsSource(
            name="E2E wire", kind="rss", url="https://wire.example/feed.xml",
            trust_weight=Decimal("0.7"), enabled=False,
        )  # fmt: skip
        db.add(source)
        db.flush()

        def story(title: str, summary: str, affects: bool) -> NewsCluster:
            cluster = NewsCluster(
                title=title, first_seen=now, last_seen=now, relevance=Decimal("0.8"),
                max_impact=74, linked=True, assessed=True, affects_owner=affects,
            )  # fmt: skip
            db.add(cluster)
            db.flush()
            db.add(
                NewsItem(
                    source_id=source.id,
                    canonical_url=f"https://wire.example/{cluster.id}",
                    title=title,
                    summary=summary,
                    published_at=now,
                    content_hash=f"e2e-{cluster.id}",
                    cluster_id=cluster.id,
                )
            )
            db.add(
                NewsLink(
                    cluster_id=cluster.id, instrument_id=instrument.id, link_type="direct",
                    relevance=Decimal("0.8"), matched_by="alias:e2e",
                )
            )  # fmt: skip
            return cluster

        shown = story(
            "E2E story: export limits on chip tools widen",
            "The government widened limits on exports of chip-making tools.",
            True,
        )
        db.add(
            NewsAssessment(
                cluster_id=shown.id, impact_score=74, direction="negative", horizon="weeks",
                affected=[f"instrument:{instrument.id}"],
                rationale="Orders for the direct holding could be cut.",
                confidence="medium", model="claude-sonnet-5-5",
                outlook_term="mid", outlook_level="high",
                outlook="Orders could fall over the coming quarters.",
                advice="Watch the sleeve drift; consider directing new money elsewhere first.",
            )
        )  # fmt: skip
        hidden = story("E2E story: a fishing quota debate", "Parliament debated quotas.", False)
        db.add(
            NewsAssessment(
                cluster_id=hidden.id, impact_score=3, direction="unclear", horizon="days",
                affected=[], rationale="No bearing on the holdings.", confidence="high",
                model="claude-sonnet-5-5",
            )
        )  # fmt: skip
        db.commit()


if __name__ == "__main__":
    main()
