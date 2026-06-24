import httpx

from src import scraper


def _client_returning(*responses: httpx.Response) -> tuple[httpx.Client, list[int]]:
    """Build a client whose nth request returns responses[n]."""
    calls = [0]

    def handler(_req: httpx.Request) -> httpx.Response:
        i = calls[0]
        calls[0] = i + 1
        return responses[i]

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_429_honors_retry_after(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: sleeps.append(s))

    client, calls = _client_returning(
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"ok": True}),
    )
    resp = scraper._get_with_retry(client, "https://x/y")
    assert resp.status_code == 200
    assert calls[0] == 2
    assert sleeps == [3]


def test_5xx_backs_off_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: sleeps.append(s))

    client, calls = _client_returning(
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    )
    resp = scraper._get_with_retry(client, "https://x/y")
    assert resp.status_code == 200
    assert calls[0] == 3
    # backoff = 2**0, 2**1
    assert sleeps == [1, 2]


def test_2xx_first_try_no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: sleeps.append(s))

    client, calls = _client_returning(httpx.Response(200, json={"ok": True}))
    resp = scraper._get_with_retry(client, "https://x/y")
    assert resp.status_code == 200
    assert calls[0] == 1
    assert sleeps == []
