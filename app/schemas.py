from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Theme(str, Enum):
    tourism_strategy = "national_tourism_strategy_and_visitor_numbers"
    giga_projects = "destination_and_giga_project_launches"
    aviation_visa = "aviation_visa_and_entry_policy"
    reputational_risk = "reputational_risk_or_negative_coverage"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ---- Structured output the LLM must return for each article (schema-validated) ----
# Field order matters: structured outputs are generated in schema order, so the
# model commits to evidence and a justification *before* it assigns scores.
class ClassificationResult(BaseModel):
    relevant: bool = Field(..., description="False if the article has nothing to do with Saudi tourism, travel, destinations, aviation/visas, or the entity's reputation")
    evidence_quote: str = Field(..., description="Short verbatim quote from the article text that most directly supports the classification")
    justification: str = Field(..., min_length=10, max_length=400, description="One sentence a non-technical communications director could understand")
    themes: list[Theme] = Field(..., description="Every matching priority theme; empty only if relevant is false")
    sentiment: Sentiment
    priority: Priority
    risk_score: float = Field(..., ge=0.0, le=1.0, description="0=no reputational risk, 1=severe")


# ---- Ingest ----
class IngestRequest(BaseModel):
    source_urls: list[str] | None = None  # optional override; defaults to configured feed list


class IngestResponse(BaseModel):
    fetched: int
    new_articles: int
    duplicates: int
    errors: int
    filtered_out: int = 0          # too old, or failed the keyword gate
    feeds: list[dict] = []         # per-feed status, so a dead feed is visible, not silent
    dedupe: dict = {}


# ---- Classify ----
class ClassifyRequest(BaseModel):
    article_ids: list[int] | None = None  # None = classify all un-classified articles


class ClassifyResponse(BaseModel):
    classified: int
    high_risk_flagged: int
    errors: int


# ---- Briefing ----
class BriefingRequest(BaseModel):
    briefing_date: date | None = None  # defaults to today
    # Synthetic fixtures must never reach a real briefing; only the offline demo opts in.
    include_synthetic: bool = False


class Citation(BaseModel):
    claim: str
    article_id: int
    source: str
    url: str
    supported: bool  # set by the verifier step


class BriefingResponse(BaseModel):
    briefing_id: int
    status: str
    content_md: str
    citations: list[Citation]
    unverified_claim_count: int


# ---- Alerts ----
class AlertPayload(BaseModel):
    article_id: int
    title: str
    source: str
    url: str
    risk_score: float
    reason: str
    themes: list[Theme]


# ---- Ask (RAG Q&A) ----
class AskRequest(BaseModel):
    question: str = Field(..., min_length=3)
    top_k: int = 8


class AskSource(BaseModel):
    article_id: int
    title: str
    source: str
    url: str
    published_at: datetime | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    found: bool  # False if nothing relevant was retrieved — must not fabricate an answer
