import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article
from app.services.embeddings import embed_query


SEMANTIC_MIN_SIM = 0.78


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def hybrid_search(db: Session, query: str, top_k: int = 8) -> list[Article]:
    """
    BM25 over titles+text for lexical matches (good for names, dates,
    exact terms) combined with embedding similarity for semantic matches
    (good for paraphrased questions). Reciprocal-rank fusion of the two
    rankings — simple, no tuning of a blend weight needed.
    """
    articles = db.execute(
        select(Article).where(Article.clean_text.is_not(None))
    ).scalars().all()

    if not articles:
        return []

    corpus = [f"{a.title} {a.clean_text or ''}" for a in articles]
    tokenized_corpus = [_tokenize(t) for t in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = bm25.get_scores(_tokenize(query))
    # only documents that actually share a term with the query count as lexical hits
    bm25_rank = [i for i in np.argsort(-bm25_scores) if bm25_scores[i] > 0]

    embedded = [(i, a) for i, a in enumerate(articles) if a.embedding is not None]
    if embedded:
        q_vec = np.array(embed_query(query))
        idxs = [i for i, _ in embedded]
        matrix = np.array([a.embedding for _, a in embedded])
        sims = matrix @ q_vec
        # e5 cosine scores sit in a compressed ~0.7-0.9 band; below ~0.78 is noise.
        sem_order = [idxs[i] for i in np.argsort(-sims) if sims[i] >= SEMANTIC_MIN_SIM]
    else:
        sem_order = []

    # reciprocal rank fusion
    k = 60
    scores: dict[int, float] = {}
    for rank, idx in enumerate(bm25_rank):
        scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)
    for rank, idx in enumerate(sem_order):
        scores[idx] = scores.get(idx, 0) + 1 / (k + rank + 1)

    ranked_idxs = sorted(scores.keys(), key=lambda i: -scores[i])[:top_k]
    return [articles[i] for i in ranked_idxs]
