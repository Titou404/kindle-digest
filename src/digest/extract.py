"""Extract the main text of an article page."""

import httpx
import trafilatura


def extract_text(client: httpx.Client, url: str) -> str:
    """Return the article text, or "" if none was found (e.g. paywall page)."""
    response = client.get(url)
    response.raise_for_status()
    return trafilatura.extract(response.text, url=url) or ""
