import httpx
import pytest

from src import scraper


@pytest.fixture
def no_sleep(monkeypatch):
    """Avoid real time.sleep() delays during retry tests."""
    monkeypatch.setattr(scraper.time, "sleep", lambda *a, **k: None)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _article(aid: int, draft: bool = False) -> dict:
    return {
        "id": aid,
        "title": f"Article {aid}",
        "body": f"<p>body {aid}</p>",
        "html_url": f"https://support.example.com/hc/articles/{aid}",
        "edited_at": "2024-01-01T00:00:00Z",
        "draft": draft,
    }


def test_get_with_retry_recovers_from_429(no_sleep):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"articles": []})

    client = _mock_client(handler)
    resp = scraper._get_with_retry(client, "https://x/api", params=None)

    assert resp.status_code == 200
    assert calls["n"] == 2  # throttled once, then succeeded


def test_get_with_retry_recovers_from_5xx(no_sleep):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"articles": []})

    client = _mock_client(handler)
    resp = scraper._get_with_retry(client, "https://x/api", params=None)

    assert resp.status_code == 200
    assert calls["n"] == 2


def test_get_with_retry_raises_after_exhausting_retries(no_sleep):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = _mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        scraper._get_with_retry(client, "https://x/api", params=None)

    assert calls["n"] == scraper.MAX_RETRIES  # initial + retries within the loop


def test_get_with_retry_honors_retry_after_header(monkeypatch):
    """429 with Retry-After should sleep exactly that many seconds, not the backoff default."""
    slept = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: slept.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"})

    client = _mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        scraper._get_with_retry(client, "https://x/api", params=None)

    assert slept and all(s == 7 for s in slept)  # every backoff honored Retry-After=7


def test_fetch_all_skips_drafts_and_normalizes(monkeypatch):
    """End-to-end: drafts filtered out, id coerced to str, next_page terminates."""
    pages = iter([
        httpx.Response(200, json={
            "articles": [_article(1, draft=False), _article(2, draft=True)],
            "next_page": "https://x/api?page=2",
        }),
        httpx.Response(200, json={"articles": [_article(3)], "next_page": None}),
    ])
    real_client = httpx.Client

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(lambda r: next(pages)), **kwargs)

    monkeypatch.setattr(scraper.httpx, "Client", factory)
    articles = scraper.fetch_all()

    assert [a.id for a in articles] == ["1", "3"]
    assert all(isinstance(a.id, str) for a in articles)
