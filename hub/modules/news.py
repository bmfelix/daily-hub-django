import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from .base import HubModule

FEED_URL = "https://news.google.com/rss"
FEED_PARAMS = {"hl": "en-US", "gl": "US", "ceid": "US:en"}  # US top stories, in English


def parse_feed(xml):
    """The stories in a Google News RSS feed, in order: title, link, source, and when it was published."""
    stories = []
    for item in ET.fromstring(xml).iter("item"):
        source = item.find("source")
        stories.append({
            "title": item.findtext("title", ""),
            "link": item.findtext("link", ""),
            "published": item.findtext("pubDate", ""),
            "source": source.text if source is not None and source.text else "",
        })
    return stories


class GoogleNewsClient:
    """Reads Google News' public top-stories feed (RSS), which needs no key."""

    timeout = 8

    def top_stories(self, limit=20):
        response = requests.get(FEED_URL, params=FEED_PARAMS, timeout=self.timeout, headers={"User-Agent": "DailyHub/1.0"})
        response.raise_for_status()
        return parse_feed(response.content)[:limit]


def headline(item):
    """Google adds " - Source" to every title; the page shows the source on its own line instead."""
    suffix = f" - {item['source']}"
    title = item["title"]
    return title[: -len(suffix)] if item["source"] and title.endswith(suffix) else title


def published(item):
    try:
        return parsedate_to_datetime(item["published"])
    except (TypeError, ValueError):
        return None


class NewsModule(HubModule):
    slug = "news"
    title = "News"
    summary = "Top stories from Google News."

    live_card = True
    client_class = GoogleNewsClient

    def load(self):
        try:
            items = self.client_class().top_stories()
        except (requests.RequestException, ET.ParseError):
            return {"error": "The news service did not respond. Try again shortly."}

        stories = [
            {"title": headline(item), "url": item["link"], "source": item["source"], "published": published(item)}
            for item in items
        ]
        return {"stories": stories}
