import logging
import math
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, NotFoundError, OpenAI

from . import config

log = logging.getLogger("megatronbot")

# OpenAI default static chunking (documented). Kept here so the estimate and
# the upload settings stay in sync — if you change one, change the other.
CHUNK_MAX_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 400

# Under parallel load, the first poll after attach occasionally races with
# OpenAI's eventual consistency and returns 404 for a file that was just
# successfully created. SDK doesn't retry 4xx by default — we do it ourselves.
UPLOAD_MAX_ATTEMPTS = 3

# load_remote_state is the most critical entry point — without it, delta logic
# can't run. Wrap with longer backoff (10s/30s/60s) on top of the SDK's own
# short-burst retries, because OpenAI's "System is overloaded" 503s typically
# last minutes, not seconds, and observably hit our daily window.
LOAD_STATE_MAX_ATTEMPTS = 3
LOAD_STATE_BACKOFF_SECONDS = (10, 30, 60)
_TRANSIENT_OPENAI_ERRORS = (InternalServerError, APIConnectionError, APITimeoutError)

# Bump SDK auto-retry from default 2 → 5 to ride out short transient blips
# before the longer app-level retry on load_remote_state kicks in.
client = OpenAI(api_key=config.OPENAI_API_KEY, max_retries=5)


def load_remote_state() -> dict:
    """Rebuild delta state from the vector store itself (attributes per file).

    Makes the daily job stateless — no persisted articles.json needed across runs.
    Returns: { article_id: {"hash", "url", "file_id"} }
    """
    last_err: Exception | None = None
    for attempt in range(LOAD_STATE_MAX_ATTEMPTS):
        try:
            return _load_remote_state_inner()
        except _TRANSIENT_OPENAI_ERRORS as e:
            last_err = e
            if attempt + 1 >= LOAD_STATE_MAX_ATTEMPTS:
                break
            wait = LOAD_STATE_BACKOFF_SECONDS[attempt]
            log.warning(
                "load_remote_state attempt %d/%d failed (%s) — sleeping %ds",
                attempt + 1, LOAD_STATE_MAX_ATTEMPTS, type(e).__name__, wait,
            )
            time.sleep(wait)
    assert last_err is not None
    raise last_err


def _load_remote_state_inner() -> dict:
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
    """Upload a markdown file to Files API, then attach to the vector store.

    Retries on transient `NotFoundError` from the post-attach poll — observed
    in production on DigitalOcean under parallel load. On retry, we delete
    the previous Files-API object so it doesn't leak.
    """
    last_err: Exception | None = None
    for attempt in range(UPLOAD_MAX_ATTEMPTS):
        file_obj = None
        try:
            with open(path, "rb") as fh:
                file_obj = client.files.create(file=fh, purpose="assistants")
            client.vector_stores.files.create_and_poll(
                vector_store_id=config.VECTOR_STORE_ID,
                file_id=file_obj.id,
                attributes={"article_id": str(article_id), "hash": content_hash, "url": url},
            )
            return file_obj.id
        except NotFoundError as e:
            last_err = e
            log.warning(
                "404 race on upload attempt %d/%d for %s — retrying",
                attempt + 1, UPLOAD_MAX_ATTEMPTS, path,
            )
            if file_obj is not None:
                try:
                    client.files.delete(file_obj.id)
                except Exception:
                    pass
            time.sleep(2**attempt)
    assert last_err is not None
    raise last_err


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
