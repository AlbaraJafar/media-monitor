"""
Single choke point for every LLM call — and the only file that knows which
vendor is behind a model name.

Provider is chosen per call from the model name ("claude-*" -> Anthropic,
"gemini-*" -> Google, "humain-*" -> HUMAIN Node, anything else -> OpenAI), so switching vendors is a config change, and the
fallback model can deliberately sit at a *different* vendor: a single-provider
outage then degrades the briefing to the backup model instead of killing it.

Reliability layers (the "what happens at 06:45" story, per call):
  1. Transport: each SDK retries 429 / 5xx / connection errors with backoff.
  2. Output: structured outputs constrain the response to the Pydantic schema;
     if validation still fails (or the model refuses / truncates) we retry.
  3. Model: call_text() falls back to a secondary model if the primary fails.
Pipeline-level degradation (DEGRADED briefing) lives in services/briefing.py.

Every call writes a `runs` row with model + token counts, which is what the
cost report (/runs/summary) is computed from.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import anthropic
import openai
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import Run

logger = logging.getLogger("llm")

# Transport-level failures from either vendor (after the SDK's own retries).
API_ERRORS = (anthropic.APIError, openai.APIError)

# Anthropic models that support the server-side refusal fallback ("default" routing).
_ANTHROPIC_SERVER_FALLBACK = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}


class LLMOutputError(Exception):
    """Model responded, but not with something we can use (schema mismatch, refusal, truncation)."""


@dataclass
class _Result:
    text: str
    parsed: BaseModel | None
    input_tokens: int | None
    output_tokens: int | None
    problem: str | None  # set when the output is unusable (refusal, truncation, ...)


def _is_anthropic(model: str) -> bool:
    return model.startswith("claude-")


@lru_cache(maxsize=1)
def _anthropic() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None, max_retries=3, timeout=180.0)


@lru_cache(maxsize=1)
def _openai() -> openai.OpenAI:
    return openai.OpenAI(api_key=settings.openai_api_key or None, max_retries=3, timeout=180.0)


# ---------------------------------------------------------------- Anthropic --

def _anthropic_call(model: str, system: str, user_prompt: str, max_tokens: int,
                    schema: type[BaseModel] | None) -> _Result:
    messages = [{"role": "user", "content": user_prompt}]
    if schema is not None:
        r = _anthropic().messages.parse(model=model, max_tokens=max_tokens, system=system,
                                        messages=messages, output_format=schema)
        parsed = r.parsed_output
    elif model in _ANTHROPIC_SERVER_FALLBACK:
        # If the model declines (e.g. a classifier false positive on crisis coverage),
        # the API re-runs the request on a fallback model inside the same call.
        r = _anthropic().beta.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages,
                                              betas=["server-side-fallback-2026-07-01"],
                                              extra_body={"fallbacks": "default"})
        parsed = None
    else:
        r = _anthropic().messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
        parsed = None

    text = "".join(b.text for b in r.content if b.type == "text")
    problem = f"stop_reason={r.stop_reason}" if r.stop_reason in ("refusal", "max_tokens") else None
    if schema is not None and parsed is None:
        problem = problem or "no parsed output"
    return _Result(text, parsed, r.usage.input_tokens, r.usage.output_tokens, problem)


# ------------------------------------------------------------------- OpenAI --

def _openai_call(model: str, system: str, user_prompt: str, max_tokens: int,
                 schema: type[BaseModel] | None, reasoning_effort: str | None) -> _Result:
    kwargs = dict(
        model=model,
        instructions=system,
        input=user_prompt,
        max_output_tokens=max_tokens,
        # Don't persist article text / briefings on the vendor side beyond what the
        # API requires — the data-handling story says the pipeline holds the record.
        store=False,
    )
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}

    if schema is not None:
        r = _openai().responses.parse(text_format=schema, **kwargs)
        parsed = r.output_parsed
    else:
        r = _openai().responses.create(**kwargs)
        parsed = None

    problem = None
    if r.status != "completed":
        reason = r.incomplete_details.reason if r.incomplete_details else r.status
        problem = f"status={r.status} reason={reason}"
    elif any(c.type == "refusal" for item in r.output if item.type == "message" for c in item.content):
        problem = "refusal"
    elif schema is not None and parsed is None:
        problem = "no parsed output"

    usage = r.usage
    return _Result(r.output_text or "", parsed, getattr(usage, "input_tokens", None),
                   getattr(usage, "output_tokens", None), problem)


# ------------------------------------------- OpenAI-compatible third parties --
# Vendors that expose an OpenAI-compatible *Chat Completions* endpoint (not the
# Responses API). model-name prefix -> (base_url, settings attribute holding the key)
_COMPAT_VENDORS = {
    "gemini-": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini_api_key"),
    # HUMAIN Node: in-Kingdom hosting option; humain-m3 is in approved-access preview.
    "humain-": ("https://api.node.humain.com/v1", "humain_api_key"),
}


def _compat_vendor(model: str) -> tuple[str, str] | None:
    return next((v for prefix, v in _COMPAT_VENDORS.items() if model.startswith(prefix)), None)


@lru_cache(maxsize=None)
def _compat_client(base_url: str, key_attr: str) -> openai.OpenAI:
    return openai.OpenAI(base_url=base_url, api_key=getattr(settings, key_attr) or "missing",
                         max_retries=3, timeout=180.0)


def _compat_call(model: str, system: str, user_prompt: str, max_tokens: int,
                 schema: type[BaseModel] | None, reasoning_effort: str | None) -> _Result:
    client = _compat_client(*_compat_vendor(model))
    kwargs = dict(model=model, max_tokens=max_tokens,
                  messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}])
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    if schema is not None:
        r = client.chat.completions.parse(response_format=schema, **kwargs)
    else:
        r = client.chat.completions.create(**kwargs)

    choice = r.choices[0]
    msg = choice.message
    parsed = getattr(msg, "parsed", None) if schema is not None else None
    problem = None
    if choice.finish_reason in ("length", "content_filter"):
        problem = f"finish_reason={choice.finish_reason}"
    elif getattr(msg, "refusal", None):
        problem = "refusal"
    elif schema is not None and parsed is None:
        problem = "no parsed output"
    usage = r.usage
    return _Result(msg.content or "", parsed, getattr(usage, "prompt_tokens", None),
                   getattr(usage, "completion_tokens", None), problem)


# ------------------------------------------------------------ shared plumbing --

def _call(model: str, system: str, user_prompt: str, max_tokens: int,
          schema: type[BaseModel] | None = None, reasoning_effort: str | None = None) -> _Result:
    if _is_anthropic(model):
        return _anthropic_call(model, system, user_prompt, max_tokens, schema)
    if _compat_vendor(model):
        return _compat_call(model, system, user_prompt, max_tokens, schema, reasoning_effort)
    return _openai_call(model, system, user_prompt, max_tokens, schema, reasoning_effort)


def _log_run(db: Session, step: str, model: str, status: str, started: datetime, t0: float,
             result: _Result | None = None, detail: str | None = None) -> None:
    db.add(Run(
        step=step, status=status, model=model, detail=detail,
        input_tokens=result.input_tokens if result else None,
        output_tokens=result.output_tokens if result else None,
        latency_ms=int((time.monotonic() - t0) * 1000),
        started_at=started, finished_at=datetime.now(timezone.utc),
    ))
    db.commit()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(LLMOutputError),
    reraise=True,
)
def call_structured(
    db: Session,
    step: str,
    model: str,
    system: str,
    user_prompt: str,
    schema: type[BaseModel],
    max_tokens: int = 2048,
    reasoning_effort: str | None = None,
) -> BaseModel:
    """Calls the model with structured outputs and returns a validated `schema` instance."""
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    try:
        result = _call(model, system, user_prompt, max_tokens, schema, reasoning_effort)
    except (ValidationError, ValueError) as exc:
        _log_run(db, step, model, "error", started, t0, detail=f"schema validation failed: {exc}"[:2000])
        raise LLMOutputError(str(exc)) from exc
    except API_ERRORS as exc:
        _log_run(db, step, model, "error", started, t0, detail=f"api error: {exc}"[:2000])
        raise

    if result.problem:
        _log_run(db, step, model, "error", started, t0, result, detail=f"unusable output: {result.problem}")
        raise LLMOutputError(result.problem)

    _log_run(db, step, model, "ok", started, t0, result)
    return result.parsed


def call_text(db: Session, step: str, model: str, system: str, user_prompt: str,
              max_tokens: int = 16000, fallback_model: str | None = None,
              reasoning_effort: str | None = None) -> str:
    """Free-text call with a secondary-model fallback. Raises only if every model fails."""
    models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
    last_exc: Exception | None = None

    for m in models:
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        try:
            result = _call(m, system, user_prompt, max_tokens, reasoning_effort=reasoning_effort)
        except API_ERRORS as exc:
            _log_run(db, step, m, "error", started, t0, detail=f"api error: {exc}"[:2000])
            logger.warning("%s failed on %s: %s", step, m, exc)
            last_exc = exc
            continue

        if result.problem or not result.text.strip():
            _log_run(db, step, m, "error", started, t0, result, detail=f"unusable output: {result.problem or 'empty'}")
            last_exc = LLMOutputError(f"{m}: {result.problem or 'empty'}")
            continue

        _log_run(db, step, m, "ok" if m == model else "degraded", started, t0, result,
                 detail=None if m == model else f"served by fallback model {m}")
        return result.text

    raise last_exc or LLMOutputError("no model produced output")
