import sys

from src import config, delta, markdownifier, scraper, state as state_mod, utils, vector_store

log = utils.configure_logging()


def run() -> int:
    log.info("=== OptiBot KB sync started ===")

    remote_articles = scraper.fetch_all()
    log.info("Scraped %d articles", len(remote_articles))
    if len(remote_articles) < config.MIN_ARTICLES:
        log.warning("Only %d articles (< %d expected)", len(remote_articles), config.MIN_ARTICLES)

    prev_state = vector_store.load_remote_state()  # source of truth = vector store
    counts = {"added": 0, "updated": 0, "skipped": 0, "removed": 0}
    chunks_embedded = 0
    snapshot: dict = {}

    for art in remote_articles:
        md_text = markdownifier.to_markdown(art)
        content_hash = utils.sha256(md_text)
        slug = markdownifier.slug_for(art)
        prev = prev_state.get(art.id)
        action = delta.classify(content_hash, prev)

        if action == "added":
            path = markdownifier.write(slug, md_text)
            file_id = vector_store.upload(path, article_id=art.id, content_hash=content_hash, url=art.url)
            chunks_embedded += vector_store.estimate_chunks(md_text)
        else:  # updated | skipped — both require an existing prev entry
            assert prev is not None, "classify returns updated/skipped only when prev exists"
            prev_file_id: str = prev["file_id"]
            if action == "updated":
                vector_store.delete(prev_file_id)  # OpenAI has no "replace"
                path = markdownifier.write(slug, md_text)
                file_id = vector_store.upload(path, article_id=art.id, content_hash=content_hash, url=art.url)
                chunks_embedded += vector_store.estimate_chunks(md_text)
            else:  # skipped
                file_id = prev_file_id
                markdownifier.write(slug, md_text)  # keep local evidence fresh

        counts[action] += 1
        snapshot[art.id] = {
            "slug": slug, "url": art.url, "edited_at": art.edited_at,
            "hash": content_hash, "file_id": file_id,
        }

    # Remove articles that disappeared upstream.
    remote_ids = {a.id for a in remote_articles}
    for article_id, meta in prev_state.items():
        if article_id not in remote_ids:
            vector_store.delete(meta["file_id"])
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
