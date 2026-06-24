import logging
import time
from dataclasses import dataclass

import httpx

from . import config

log = logging.getLogger("megatronbot")

# Retry policy for the Zendesk list endpoint. The public help-center API
# rate-limits aggressively from shared cloud IPs (DigitalOcean, in our case),
# returning 429 with a Retry-After header. We honor it and back off on 5xx.
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2


def _get_with_retry(client: httpx.Client, url: str, params=None) -> httpx.Response:
    for attempt in range(MAX_RETRIES):
        resp = client.get(url, params=params)
        last = attempt == MAX_RETRIES - 1
        if resp.status_code == 429:
            if last:
                resp.raise_for_status()  # retries exhausted — surface the 429
            wait = int(resp.headers.get("Retry-After", BACKOFF_BASE_SECONDS**attempt))
            log.warning("429 from Zendesk, sleeping %ds (attempt %d/%d)", wait, attempt + 1, MAX_RETRIES)
            time.sleep(wait)
            continue
        if 500 <= resp.status_code < 600:
            if last:
                resp.raise_for_status()  # retries exhausted
            wait = BACKOFF_BASE_SECONDS**attempt
            log.warning("%d from Zendesk, sleeping %ds (attempt %d/%d)", resp.status_code, wait, attempt + 1, MAX_RETRIES)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("retry loop exited without a response")  # MAX_RETRIES >= 1


@dataclass
class Article:
    id: str
    title: str
    body_html: str
    url: str
    edited_at: str


def fetch_all() -> list[Article]:
    """Fetch published articles for the configured locale.

    The list endpoint already returns the article body, so one paginated
    sweep is enough — no per-article request needed.
    """
    url = (
        f"{config.ZENDESK_BASE_URL}/api/v2/help_center/"
        f"{config.ZENDESK_LOCALE}/articles.json"
    )
    params = {"per_page": config.PER_PAGE, "sort_by": "updated_at", "sort_order": "desc"}
    articles: list[Article] = []

    with httpx.Client(timeout=30.0) as client:
        while url:
            resp = _get_with_retry(client, url, params=params)
            data = resp.json()
            for a in data.get("articles", []):
                if a.get("draft"):
                    continue
                articles.append(
                    Article(
                        id=str(a["id"]),
                        title=a["title"],
                        body_html=a.get("body") or "",
                        url=a["html_url"],
                        edited_at=a["edited_at"],
                    )
                )
            url = data.get("next_page")
            params = None  # next_page already carries query params
    return articles
