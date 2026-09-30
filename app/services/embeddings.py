import threading
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import settings


_load_lock = threading.Lock()


# Loaded once per process. Local + multilingual so Arabic and English
# articles share one vector space, and nothing leaves the container
# for this step — relevant to the "data stays in the client environment" story.
@lru_cache(maxsize=1)
def _load() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model_name)


def get_embedder() -> SentenceTransformer:
    with _load_lock:  # startup warm-up thread and the first request must not both load 2GB of weights
        return _load()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_embedder()
    # e5 models expect a "passage:" / "query:" prefix convention for best results
    prefixed = [f"passage: {t}" for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    model = get_embedder()
    vector = model.encode(f"query: {text}", normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()
