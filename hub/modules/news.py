import requests

from .base import HubModule

SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsClient:
    """Talks to the Hacker News search API (by Algolia), which needs no key."""

    timeout = 8

    def front_page(self, limit=20):
        response = requests.get(
            SEARCH_URL, params={"tags": "front_page", "hitsPerPage": limit}, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["hits"]


class NewsModule(HubModule):
    slug = "news"
    title = "News"
    summary = "Top headlines from the Hacker News front page."

    client_class = HackerNewsClient

    def load(self):
        try:
            hits = self.client_class().front_page()
        except requests.RequestException:
            return {"error": "The news service did not respond. Try again shortly."}

        stories = [
            {
                "title": hit["title"],
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "discussion": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "points": hit.get("points", 0),
                "comments": hit.get("num_comments") or 0,
                "author": hit["author"],
            }
            for hit in hits
        ]
        return {"stories": stories}
