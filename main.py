import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from src import config, delta, markdownifier, scraper, state as state_mod, utils, vector_store

log = utils.configure_logging()

# Each upload is ~12s wall-clock (mostly waiting on OpenAI to embed). Sequentially
# that's 401 × 12s ≈ 80 min for a fresh load. Run them in a thread pool to overlap
# the waits — the openai client is httpx-backed and thread-safe. Tunable via env
# for ops to throttle if a future tier hit rate-limits us.
MAX_UPLOAD_WORKERS = int(os.getenv("MAX_UPLOAD_WORKERS", "8"))


def _do_upload(art, md_text, content_hash, slug, prev_file_id):
    """Worker: optionally delete the previous file, then upload the new one."""
    if prev_file_id is not None:
        vector_store.delete(prev_file_id)  # OpenAI has no in-place replace
    path = markdownifier.write(slug, md_text)
    file_id = vector_store.upload(
        path, article_id=art.id, content_hash=content_hash, url=art.url
    )
    return file_id, vector_store.estimate_chunks(md_text)


def run() -> int:
    log.info("=== OptiBot KB sync started ===")

    remote_articles = scraper.fetch_all()
    log.info("Scraped %d articles", len(remote_articles))
    if len(remote_articles) < config.MIN_ARTICLES:
        log.warning("Only %d articles (< %d expected)", len(remote_articles), config.MIN_ARTICLES)

    prev_state = vector_store.load_remote_state()
    counts = {"added": 0, "updated": 0, "skipped": 0, "removed": 0}
    chunks_embedded = 0
    snapshot: dict = {}

    # Pass 1 (sequential, cheap): classify + write markdown to disk. Skipped
    # articles finalize here; added/updated are queued for the parallel pass.
    upload_jobs: list[tuple] = []  # (action, art, md_text, content_hash, slug, prev_file_id)
    for art in remote_articles:
        md_text = markdownifier.to_markdown(art)
        content_hash = utils.sha256(md_text)
        slug = markdownifier.slug_for(art)
        prev = prev_state.get(art.id)
        action = delta.classify(content_hash, prev)

        if action == "skipped":
            assert prev is not None
            markdownifier.write(slug, md_text)  # keep local evidence fresh
            counts["skipped"] += 1
            snapshot[art.id] = {
                "slug": slug, "url": art.url, "edited_at": art.edited_at,
                "hash": content_hash, "file_id": prev["file_id"],
            }
        else:
            prev_file_id = prev["file_id"] if prev else None
            upload_jobs.append((action, art, md_text, content_hash, slug, prev_file_id))

    # Pass 2 (parallel): run uploads concurrently to overlap embedding wait time.
    if upload_jobs:
        log.info("Uploading %d files with %d workers", len(upload_jobs), MAX_UPLOAD_WORKERS)
        with ThreadPoolExecutor(max_workers=MAX_UPLOAD_WORKERS) as pool:
            futures = {
                pool.submit(_do_upload, art, md_text, content_hash, slug, prev_file_id):
                    (action, art, content_hash, slug)
                for (action, art, md_text, content_hash, slug, prev_file_id) in upload_jobs
            }
            try:
                for fut in as_completed(futures):
                    action, art, content_hash, slug = futures[fut]
                    file_id, n_chunks = fut.result()
                    counts[action] += 1
                    chunks_embedded += n_chunks
                    snapshot[art.id] = {
                        "slug": slug, "url": art.url, "edited_at": art.edited_at,
                        "hash": content_hash, "file_id": file_id,
                    }
            except Exception:
                # Cancel pending uploads so we exit fast on the first failure.
                pool.shutdown(wait=False, cancel_futures=True)
                raise

    # Pass 3 (parallel): drop files for articles that disappeared upstream.
    remote_ids = {a.id for a in remote_articles}
    orphans = [m["file_id"] for aid, m in prev_state.items() if aid not in remote_ids]
    if orphans:
        log.info("Deleting %d orphan files", len(orphans))
        with ThreadPoolExecutor(max_workers=MAX_UPLOAD_WORKERS) as pool:
            for _ in pool.map(vector_store.delete, orphans):
                counts["removed"] += 1

    state_mod.save(snapshot)
    log.info("RESULT: %s | chunks_embedded=%d", counts, chunks_embedded)
    log.info("=== done ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())          # exit 0 only on success
    except Exception:
        log.exception("Sync failed")
        sys.exit(1)              # non-zero so the cron run is marked failed
