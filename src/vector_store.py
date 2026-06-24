import math

from openai import OpenAI

from . import config

# OpenAI default static chunking (documented). Kept here so the estimate and
# the upload settings stay in sync — if you change one, change the other.
CHUNK_MAX_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 400

client = OpenAI(api_key=config.OPENAI_API_KEY)


def load_remote_state() -> dict:
    """Rebuild delta state from the vector store itself (attributes per file).

    Makes the daily job stateless — no persisted articles.json needed across runs.
    Returns: { article_id: {"hash", "url", "file_id"} }
    """
    state: dict = {}
    after: str | None = None
    while True:
        kwargs: dict = {"limit": 100}
        if after is not None:
            kwargs["after"] = after
        page = client.vector_stores.files.list(
            vector_store_id=config.VECTOR_STORE_ID, **kwargs
        )
        for vsf in page.data:
            attrs = vsf.attributes or {}
            article_id = attrs.get("article_id")
            if article_id is None:
                continue
            state[str(article_id)] = {
                "hash": attrs.get("hash"),
                "url": attrs.get("url"),
                "file_id": vsf.id,
            }
        if not page.has_more:
            break
        after = page.data[-1].id
    return state


def upload(path, *, article_id: str, content_hash: str, url: str) -> str:
    """Upload a markdown file to Files API, then attach to the vector store."""
    with open(path, "rb") as fh:
        file_obj = client.files.create(file=fh, purpose="assistants")
    client.vector_stores.files.create_and_poll(
        vector_store_id=config.VECTOR_STORE_ID,
        file_id=file_obj.id,
        attributes={"article_id": str(article_id), "hash": content_hash, "url": url},
    )
    return file_obj.id


def delete(file_id: str) -> None:
    """Detach from the vector store and delete the underlying file."""
    try:
        client.vector_stores.files.delete(
            vector_store_id=config.VECTOR_STORE_ID, file_id=file_id
        )
    finally:
        client.files.delete(file_id)


def estimate_chunks(text: str) -> int:
    """Estimate chunk count for a markdown file.

    OpenAI does not expose the actual embedded chunk count — `files.content()`
    returns the whole file as a single entry, not chunks. We estimate from the
    documented chunking strategy and file length: stride = max - overlap,
    ~4 chars/token heuristic. The formula is stated in the README.
    """
    stride = CHUNK_MAX_TOKENS - CHUNK_OVERLAP_TOKENS
    tokens = max(1, len(text) // 4)
    if tokens <= CHUNK_MAX_TOKENS:
        return 1
    return 1 + math.ceil((tokens - CHUNK_MAX_TOKENS) / stride)
