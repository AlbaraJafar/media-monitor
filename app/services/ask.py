from sqlalchemy.orm import Session

from app.config import settings
from app.models import Article
from app.services.llm import call_text
from app.services.retrieval import hybrid_search

SYSTEM_PROMPT = """You answer an analyst's question using ONLY the provided \
retrieved articles. If the articles do not contain enough information to answer, \
say so plainly instead of guessing — do not use outside knowledge. Cite article \
IDs like [A123] after every claim. Keep the answer concise and in the analyst's \
language (match the language of the question)."""


def answer_question(db: Session, question: str, top_k: int = 8) -> dict:
    articles: list[Article] = hybrid_search(db, question, top_k=top_k)

    if not articles:
        return {"answer": "No relevant coverage found in the archive for this question.", "sources": [], "found": False}

    context = "\n\n".join(
        f"[A{a.id}] {a.title} — {a.source} ({a.published_at})\n{(a.clean_text or '')[:2000]}"
        for a in articles
    )
    user_prompt = f"Question: {question}\n\nRetrieved articles:\n\n{context}"

    answer = call_text(
        db=db, step="ask", model=settings.brief_model,
        system=SYSTEM_PROMPT, user_prompt=user_prompt, max_tokens=800,
    )

    found = "no relevant coverage" not in answer.lower() and "not found" not in answer.lower()

    return {
        "answer": answer,
        "sources": [
            {"article_id": a.id, "title": a.title, "source": a.source, "url": a.canonical_url, "published_at": a.published_at}
            for a in articles
        ],
        "found": found,
    }
