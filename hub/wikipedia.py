"""Artist background from English Wikipedia. Its text is CC BY-SA, so pages credit and link it."""

import re
from urllib.parse import unquote

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
USER_AGENT = "DailyHub/1.0 (https://github.com/bmfelix/daily-hub-django)"

# A page found by name only counts if its description sounds like a music act.
MUSIC_WORDS = re.compile(
    r"\b(band|singer|musician|rapper|group|duo|trio|songwriter|dj|vocalist|producer|composer|guitarist|supergroup)\b",
    re.I,
)


class WikipediaClient:
    """Finds an artist's page through MusicBrainz's links, then by name."""

    timeout = 8

    def _get(self, url, **params):
        response = requests.get(
            url, params={**params, "format": "json", "formatversion": 2},
            headers={"User-Agent": USER_AGENT}, timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def page(self, title):
        """The title, address, description, and opening text of a page, or None."""
        data = self._get(
            API_URL, action="query", titles=title, redirects=1,
            prop="extracts|info|description|pageprops|pageimages",
            exintro=1, explaintext=1, inprop="url", ppprop="disambiguation",
            piprop="thumbnail", pithumbsize=640,  # pageimages only returns free images by default
        )
        pages = data.get("query", {}).get("pages") or []
        page = pages[0] if pages else {}
        if page.get("missing") or "disambiguation" in page.get("pageprops", {}) or not page.get("extract"):
            return None
        return {
            "title": page["title"],
            "url": page["fullurl"],
            "summary": page["extract"].strip(),
            "description": page.get("description", ""),
            "image": (page.get("thumbnail") or {}).get("source", ""),
        }

    def linked_title(self, record):
        """The page title MusicBrainz links to, directly or through Wikidata."""
        wikidata = None
        for relation in record.get("relations", []):
            url = (relation.get("url") or {}).get("resource", "")
            direct = re.search(r"//en\.wikipedia\.org/wiki/(.+)$", url)
            if direct:
                return unquote(direct.group(1)).replace("_", " ")
            found = re.search(r"wikidata\.org/wiki/(Q\d+)", url)
            if found:
                wikidata = found.group(1)
        if wikidata is None:
            return None
        data = self._get(
            WIKIDATA_API_URL, action="wbgetentities", ids=wikidata, props="sitelinks", sitefilter="enwiki",
        )
        sitelinks = data.get("entities", {}).get(wikidata, {}).get("sitelinks") or {}
        return (sitelinks.get("enwiki") or {}).get("title")

    def find(self, record):
        """The Wikipedia page for a MusicBrainz artist record, or None."""
        title = self.linked_title(record)
        page = self.page(title) if title else None
        if page:
            return page
        name = record["name"]
        for candidate in (name, f"{name} (band)", f"{name} (musician)", f"{name} (singer)"):
            page = self.page(candidate)
            if page and MUSIC_WORDS.search(page["description"]):
                return page
        return None
