import re
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md
from slugify import slugify

from . import config
from .scraper import Article

# Tags whose entire subtree is noise we never want in the knowledge base.
# decompose() drops the tag AND its text, unlike markdownify's `strip=`.
_DROP_TAGS = ("script", "style", "nav", "header", "footer", "aside")


def _strip_noise(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    return str(soup)


def to_markdown(article: Article) -> str:
    """HTML body → clean Markdown, with front-matter + a visible citation line."""
    body = html_to_md(_strip_noise(article.body_html), heading_style="ATX")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    front_matter = (
        "---\n"
        f"article_id: {article.id}\n"
        f"title: {article.title}\n"
        f"url: {article.url}\n"
        f"edited_at: {article.edited_at}\n"
        "---\n\n"
    )
    # Visible line so File Search surfaces the URL in the prompt's "Article URL:" format.
    citation = f"Article URL: {article.url}\n\n"
    return f"{front_matter}# {article.title}\n\n{citation}{body}\n"


def slug_for(article: Article) -> str:
    """Stable, collision-free slug (include id to avoid duplicate titles)."""
    return f"{slugify(article.title)}-{article.id}"


def write(slug: str, markdown: str) -> Path:
    Path(config.ARTICLES_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(config.ARTICLES_DIR) / f"{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
