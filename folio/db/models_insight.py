"""Phase 4 tables: ETF look-through, news, calculations, agent runs and recommendations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from folio.db.base import Base, SoftDeleteMixin, utcnow
from folio.db.types import DecimalText, UTCDateTime

# --- ETF look-through (FR-MD-09) ---------------------------------------------------------------


class EtfSnapshot(Base):
    """What one ETF held on one date. A new file adds a snapshot; older ones are kept."""

    __tablename__ = "etf_snapshot"
    __table_args__ = (UniqueConstraint("instrument_id", "as_of", "source"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(10))  # csv | url | eodhd
    file_name: Mapped[str | None] = mapped_column(String(255), default=None)
    covered_pct: Mapped[Decimal] = mapped_column(DecimalText)  # weight the constituents add up to


class EtfConstituent(Base):
    __tablename__ = "etf_constituent"

    snapshot_id: Mapped[int] = mapped_column(ForeignKey("etf_snapshot.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    isin: Mapped[str | None] = mapped_column(String(12), default=None, index=True)
    ticker: Mapped[str | None] = mapped_column(String(30), default=None)
    weight_pct: Mapped[Decimal] = mapped_column(DecimalText)
    sector: Mapped[str | None] = mapped_column(String(60), default=None)
    country: Mapped[str | None] = mapped_column(String(60), default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)


class InstrumentAlias(Base):
    """A name news may use for a holding ("ASML Holding", "ASML"). Feedback moves its weight."""

    __tablename__ = "instrument_alias"
    __table_args__ = (UniqueConstraint("instrument_id", "alias"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    alias: Mapped[str] = mapped_column(String(100))
    weight: Mapped[Decimal] = mapped_column(DecimalText)  # 1 = full trust; below the floor, off


# --- News (FR-NW) ------------------------------------------------------------------------------


class NewsSource(Base, SoftDeleteMixin):
    __tablename__ = "news_source"

    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="rss")  # rss | eodhd
    url: Mapped[str] = mapped_column(String(500), default="")
    language: Mapped[str] = mapped_column(String(5), default="en")
    trust_weight: Mapped[Decimal] = mapped_column(DecimalText)  # 0.1 .. 1
    poll_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    macro_series: Mapped[Any] = mapped_column(JSON, default=list)  # series codes it speaks to
    etag: Mapped[str | None] = mapped_column(String(200), default=None)
    last_modified: Mapped[str | None] = mapped_column(String(100), default=None)
    last_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    next_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)


class NewsCluster(Base):
    """One story, as reported by one or more sources within 48 hours."""

    __tablename__ = "news_cluster"

    title: Mapped[str] = mapped_column(String(300))
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    relevance: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    max_impact: Mapped[int | None] = mapped_column(Integer, default=None)
    linked: Mapped[bool] = mapped_column(Boolean, default=False)  # the linking step has run
    assessed: Mapped[bool] = mapped_column(Boolean, default=False)


class NewsItem(Base):
    """Headline, feed summary, metadata and link only: never an article body (FR-NW-03)."""

    __tablename__ = "news_item"

    source_id: Mapped[int] = mapped_column(ForeignKey("news_source.id"), index=True)
    canonical_url: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    symbols: Mapped[Any] = mapped_column(JSON, nullable=True, default=None)  # tickers tagged
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("news_cluster.id"), default=None, index=True
    )


class NewsLink(Base):
    """A cluster's bearing on a holding (or a sleeve, for a macro story)."""

    __tablename__ = "news_link"

    cluster_id: Mapped[int] = mapped_column(ForeignKey("news_cluster.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrument.id"), default=None, index=True
    )
    sleeve: Mapped[str | None] = mapped_column(String(100), default=None)
    link_type: Mapped[str] = mapped_column(String(12))  # direct | look_through | macro | theme
    weight_pct: Mapped[Decimal | None] = mapped_column(DecimalText, default=None)
    relevance: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    matched_by: Mapped[str] = mapped_column(String(100), default="")  # the alias or rule


class NewsAssessment(Base):
    __tablename__ = "news_assessment"

    cluster_id: Mapped[int] = mapped_column(ForeignKey("news_cluster.id"), index=True)
    impact_score: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(10))  # positive | negative | mixed | unclear
    horizon: Mapped[str] = mapped_column(String(12))  # intraday | days | weeks | structural
    affected: Mapped[Any] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(6))
    model: Mapped[str] = mapped_column(String(60))
    cost_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))


class NewsFeedback(Base):
    __tablename__ = "news_feedback"

    cluster_id: Mapped[int] = mapped_column(ForeignKey("news_cluster.id"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("news_source.id"), default=None)
    verdict: Mapped[str] = mapped_column(String(12))  # useful | not_relevant


# --- Calculations, agent runs, recommendations (FR-AG) -----------------------------------------


class Calculation(Base):
    """A calculator result kept so a recommendation can point at it and be checked against it."""

    __tablename__ = "calculation"

    kind: Mapped[str] = mapped_column(String(12))  # allocator | trim | rebalance
    inputs: Mapped[Any] = mapped_column(JSON)
    plan: Mapped[Any] = mapped_column(JSON)
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id"), default=None
    )


class AgentRun(Base):
    """The full trace of one run (FR-AG, spec section 11): context, tool calls, output, cost."""

    __tablename__ = "agent_run"

    trigger: Mapped[str] = mapped_column(String(60))  # daily | event:<subject> | on_demand | news
    run_type: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(12), default="running")
    # running | ok | failed | budget
    error: Mapped[str | None] = mapped_column(Text, default=None)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    context: Mapped[Any] = mapped_column(JSON, default=dict)
    tool_calls: Mapped[Any] = mapped_column(JSON, default=list)
    findings: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[Any] = mapped_column(JSON, default=dict)  # {} until composed
    digest: Mapped[str] = mapped_column(Text, default="")


class Recommendation(Base):
    """What the agent proposes, once the validator has passed it. A refused one is kept too,
    with its reason, but is never shown as advice (FR-AG-03)."""

    __tablename__ = "recommendation"

    run_id: Mapped[int] = mapped_column(ForeignKey("agent_run.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    subjects: Mapped[Any] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    calculation_id: Mapped[int | None] = mapped_column(ForeignKey("calculation.id"), default=None)
    evidence: Mapped[Any] = mapped_column(JSON, default=list)
    sources: Mapped[Any] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(6))
    departs_from_principles: Mapped[str | None] = mapped_column(Text, default=None)
    what_would_change_this: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)
    # new | seen | accepted | rejected | snoozed | expired | refused
    refused_reason: Mapped[str | None] = mapped_column(Text, default=None)
    user_note: Mapped[str | None] = mapped_column(String(300), default=None)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    linked_transaction_ids: Mapped[Any] = mapped_column(JSON, default=list)
    price_at_creation: Mapped[Any] = mapped_column(
        JSON, default=dict
    )  # subject -> close, for FR-AG-06
    outcome: Mapped[Any] = mapped_column(JSON, default=dict)  # {} until measured (FR-AG-06)
