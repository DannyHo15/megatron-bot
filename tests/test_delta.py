from src.delta import classify


def test_buckets():
    assert classify("h1", None) == "added"
    assert classify("h2", {"hash": "h1"}) == "updated"
    assert classify("h1", {"hash": "h1"}) == "skipped"
