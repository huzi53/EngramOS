"""Lazy-singleton multilingual-e5-small embedder (384-dim, CPU). Loaded once per
process on first use — both api and bot import this but each only pays the load
cost if/when it actually enriches a capture.
"""
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
    return _model


# ponytail: e5 REQUIRES the "passage:"/"query:" prefixes + normalize_embeddings=True
# so cosine similarity is valid — omitting either silently wrecks recall. Never "simplify"
# these away.
def embed_passage(text: str) -> list[float]:
    return _get_model().encode("passage: " + text, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return _get_model().encode("query: " + text, normalize_embeddings=True).tolist()


def to_pgvector(vec: list[float]) -> str:
    # No pgvector python package — bind this string with %s::vector.
    return "[" + ",".join(map(str, vec)) + "]"
