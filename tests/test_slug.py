from src.markdownifier import slug_for
from src.scraper import Article


def _art(title, id="1"):
    return Article(id=id, title=title, body_html="", url="", edited_at="")


def test_slug_is_url_safe():
    assert slug_for(_art("How do I add a YouTube video?", "42")) == "how-do-i-add-a-youtube-video-42"


def test_same_title_different_ids_do_not_collide():
    assert slug_for(_art("Setup", "1")) != slug_for(_art("Setup", "2"))
