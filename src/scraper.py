from dataclasses import dataclass

import httpx

from . import config


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
            resp = client.get(url, params=params)
            resp.raise_for_status()
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
