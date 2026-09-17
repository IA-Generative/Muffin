from scrapling.fetchers import Fetcher


def fetch_url_markdown(url: str) -> str:
    """Single-level fetch: the page itself, rendered to clean Markdown - no
    following links, no recursive crawl (that's a later phase, if ever)."""
    page = Fetcher.get(url)
    return page.markdown()
