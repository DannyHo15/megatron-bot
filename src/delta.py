def classify(content_hash: str, prev: dict | None) -> str:
    """Bucket an article: 'added' | 'updated' | 'skipped'."""
    if prev is None:
        return "added"
    if prev.get("hash") != content_hash:
        return "updated"
    return "skipped"
