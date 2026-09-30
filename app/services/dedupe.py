from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Article
from app.services.embeddings import embed_texts


def run_dedupe(db: Session) -> dict:
    """
    Embeds any articles missing an embedding, then clusters near-duplicate
    stories (same event covered by multiple outlets) using cosine
    similarity. The first-seen article in a cluster is canonical; the
    rest are linked via cluster_id and marked is_canonical=False so the
    briefing counts each *story* once but can still say "also covered by X, Y".
    """
    to_embed = db.execute(
        select(Article).where(Article.embedding.is_(None)).where(Article.clean_text.is_not(None))
    ).scalars().all()

    if to_embed:
        texts = [f"{a.title}\n\n{(a.clean_text or '')[:2000]}" for a in to_embed]
        vectors = embed_texts(texts)
        for article, vec in zip(to_embed, vectors):
            article.embedding = vec
        db.commit()

    # New, not-yet-clustered articles...
    candidates = db.execute(
        select(Article)
        .where(Article.embedding.is_not(None))
        .where(Article.cluster_id.is_(None))
        .order_by(Article.fetched_at.asc(), Article.id.asc())
    ).scalars().all()

    if not candidates:
        return {"embedded": len(to_embed), "new_clusters": 0, "duplicates_found": 0}

    # ...compared against recent existing cluster heads, so a story that lands in
    # a later 5-minute batch still joins the cluster it belongs to. Bounded by a
    # lookback window because stories older than that aren't "the same news".
    lookback = datetime.now(timezone.utc) - timedelta(hours=settings.dedup_lookback_hours)
    heads = db.execute(
        select(Article)
        .where(Article.embedding.is_not(None))
        .where(Article.is_canonical.is_(True))
        .where(Article.cluster_id.is_not(None))
        .where(Article.fetched_at >= lookback)
    ).scalars().all()

    head_ids: list[int] = [h.id for h in heads]
    head_vecs: list[np.ndarray] = [np.asarray(h.embedding) for h in heads]
    new_clusters = duplicates_found = 0

    # embeddings are L2-normalized -> cosine similarity = dot product
    for article in candidates:
        vec = np.asarray(article.embedding)
        if head_vecs:
            sims = np.stack(head_vecs) @ vec
            best = int(np.argmax(sims))
            if sims[best] >= settings.dedup_similarity_threshold:
                article.cluster_id = head_ids[best]
                article.is_canonical = False
                duplicates_found += 1
                continue
        article.cluster_id = article.id
        article.is_canonical = True
        head_ids.append(article.id)
        head_vecs.append(vec)
        new_clusters += 1

    db.commit()
    return {"embedded": len(to_embed), "new_clusters": new_clusters, "duplicates_found": duplicates_found}
