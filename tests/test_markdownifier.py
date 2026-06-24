from src.markdownifier import to_markdown
from src.scraper import Article


def test_clean_and_preserve():
    html = '<h2>Title</h2><script>bad()</script><p>See <a href="/x">link</a></p><pre><code>x=1</code></pre>'
    art = Article(id="7", title="Doc", body_html=html, url="https://s/x", edited_at="2024")
    out = to_markdown(art)
    assert "bad()" not in out          # script removed
    assert "## Title" in out           # heading kept
    assert "](/x)" in out              # relative link kept
    assert "x=1" in out                # code kept
    assert "Article URL: https://s/x" in out  # citation present
