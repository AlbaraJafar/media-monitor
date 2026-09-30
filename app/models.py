from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction: Mapped[str] = mapped_column(Text, default="full")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=True)


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    theme: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    risk_score: Mapped[float] = mapped_column(Numeric)
    justification: Mapped[str] = mapped_column(Text)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    classification_id: Mapped[int | None] = mapped_column(ForeignKey("classifications.id"), nullable=True)
    risk_score: Mapped[float] = mapped_column(Numeric)
    reason: Mapped[str] = mapped_column(Text)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="draft")
    content_md: Mapped[str] = mapped_column(Text)
    draft_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[list] = mapped_column(JSONB, default=list)
    unverified_claims: Mapped[list] = mapped_column(JSONB, default=list)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    step: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoldLabel(Base):
    __tablename__ = "gold_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_url: Mapped[str] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    is_high_risk: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
