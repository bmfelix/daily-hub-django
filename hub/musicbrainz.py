"""Artist details from MusicBrainz, saved in the database so each artist is fetched once."""

import re
import threading
import time
import unicodedata
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.utils import timezone

from .models import Artist, ArtistName

API_URL = "https://musicbrainz.org/ws/2"
# MusicBrainz asks every app to identify itself with a name and a contact address.
USER_AGENT = "DailyHub/1.0 ( bradfelix1@gmail.com )"
ARTIST_INCLUDES = "aliases+genres+tags+ratings+url-rels+artist-rels"

REFRESH_AFTER = timedelta(days=30)  # saved artist details
RETRY_UNMATCHED_AFTER = timedelta(days=7)  # names that matched no artist


class MusicBrainzClient:
    """The MusicBrainz web service. No key, but at most one request per second."""

    timeout = 10
    min_interval = 1.1  # seconds between requests, with a little margin
    _lock = threading.Lock()
    _last_request = 0.0

    retry_delay = 3  # seconds before the one retry

    def _get(self, path, **params):
        """One request, retried once if the connection fails or MusicBrainz says to slow down (503)."""
        for attempt in (1, 2):
            try:
                response = self._send(path, params)
                if response.status_code != 503 or attempt == 2:
                    response.raise_for_status()
                    return response.json()
            except requests.ConnectionError:
                if attempt == 2:
                    raise
            time.sleep(self.retry_delay)

    def _send(self, path, params):
        with MusicBrainzClient._lock:
            wait = MusicBrainzClient._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return requests.get(
                    f"{API_URL}/{path}",
                    params={**params, "fmt": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=self.timeout,
                )
            finally:
                MusicBrainzClient._last_request = time.monotonic()

    def search_artists(self, name, limit=5):
        return self._get("artist/", query=f'artist:"{name}"', limit=limit)["artists"]

    def artist(self, mbid):
        return self._get(f"artist/{mbid}", inc=ARTIST_INCLUDES)

    def release_groups(self, mbid, pages=15):
        """Every album, EP, and single, up to `pages` × 100 (big bands have over 1,000, mostly live)."""
        groups = []
        for page in range(pages):
            data = self._get("release-group", artist=mbid, limit=100, offset=page * 100)
            groups.extend(data["release-groups"])
            if len(groups) >= data["release-group-count"]:
                break
        return groups


def normalize(name):
    """Compare names loosely: no accents, case, or punctuation."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


# Separators the stations use between several artists, as in "Tame Impala [+] Jennie".
SEPARATORS = re.compile(r"\s*(?:\[\+\]|,|&|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bx\b|/)\s*", re.I)


def name_candidates(name):
    """The full name first (for duos like "Simon & Garfunkel"), then the first listed artist."""
    name = name.strip()
    first = SEPARATORS.split(name, maxsplit=1)[0].strip()
    return [name] if first in ("", name) else [name, first]


class ArtistLibrary:
    """Finds artists by the name the radio uses. Checks the database before MusicBrainz."""

    def __init__(self, client=None):
        self.client = client or MusicBrainzClient()

    def find(self, name):
        """The saved Artist for this name, fetching it the first time. None if nothing matches."""
        key = name.strip().lower()
        entry = ArtistName.objects.select_related("artist").filter(key=key).first()
        now = timezone.now()
        if entry:
            if entry.artist and now - entry.artist.fetched_at < REFRESH_AFTER:
                return entry.artist
            if entry.artist is None and now - entry.checked_at < RETRY_UNMATCHED_AFTER:
                return None

        mbid = self.match(name)
        artist = self.save(mbid) if mbid else None
        ArtistName.objects.update_or_create(key=key, defaults={"name": name.strip(), "artist": artist, "checked_at": now})
        return artist

    def match(self, name):
        """The MusicBrainz ID whose name (or alias) really matches, or None."""
        for candidate in name_candidates(name):
            wanted = normalize(candidate)
            for result in self.client.search_artists(candidate):
                if result.get("score", 0) < 90:
                    break  # results are sorted by score
                names = [result["name"]] + [alias["name"] for alias in result.get("aliases", [])]
                if wanted in (normalize(n) for n in names):
                    return result["id"]
        return None

    def save(self, mbid):
        """Fetch and save one artist, unless the saved copy is still fresh."""
        existing = Artist.objects.filter(mbid=mbid).first()
        if existing and timezone.now() - existing.fetched_at < REFRESH_AFTER:
            return existing
        data = self.client.artist(mbid)
        release_groups = self.client.release_groups(mbid)
        artist, _ = Artist.objects.update_or_create(
            mbid=mbid,
            defaults={"name": data["name"], "data": data, "release_groups": release_groups, "fetched_at": timezone.now()},
        )
        return artist


# ---- Turning the saved record into what the artist page shows ----

LINK_GROUPS = [
    ("Listen", {"free streaming", "streaming", "youtube music", "soundcloud", "bandcamp"}),
    ("Official", {"official homepage", "blog"}),
    ("Social", {"social network", "youtube", "myspace", "fanpage", "online community", "video channel"}),
    ("Concerts", {"setlistfm", "songkick", "bandsintown", "ticketing"}),
    ("Buy", {"purchase for download", "purchase for mail-order"}),
    ("Reference", {"wikidata", "wikipedia", "allmusic", "discogs", "last.fm", "IMDb", "BBC Music page", "lyrics",
                   "secondhandsongs", "VIAF", "other databases", "discography page", "purevolume"}),
]

SITE_NAMES = {
    "open.spotify.com": "Spotify", "music.apple.com": "Apple Music", "itunes.apple.com": "iTunes",
    "music.youtube.com": "YouTube Music", "youtube.com": "YouTube", "soundcloud.com": "SoundCloud",
    "deezer.com": "Deezer", "tidal.com": "Tidal", "music.amazon.com": "Amazon Music", "napster.com": "Napster",
    "bandcamp.com": "Bandcamp", "facebook.com": "Facebook", "instagram.com": "Instagram", "twitter.com": "Twitter",
    "x.com": "X", "tiktok.com": "TikTok", "wikidata.org": "Wikidata", "wikipedia.org": "Wikipedia",
    "allmusic.com": "AllMusic", "discogs.com": "Discogs", "last.fm": "Last.fm", "imdb.com": "IMDb",
    "bbc.co.uk": "BBC Music", "genius.com": "Genius", "setlist.fm": "Setlist.fm", "songkick.com": "Songkick",
    "bandsintown.com": "Bandsintown", "ticketmaster.com": "Ticketmaster", "secondhandsongs.com": "SecondHandSongs",
    "viaf.org": "VIAF", "myspace.com": "Myspace", "play.google.com": "Google Play",
}

RELEASE_SECTIONS = ["Albums", "EPs", "Singles", "Live", "Compilations", "Other"]
CAREER_ORDER = {"Albums", "EPs"}  # oldest first; the other sections show newest first
SHOW_PER_SECTION = 60


def site_name(url):
    host = (urlparse(url).hostname or "").removeprefix("www.")
    for domain, label in SITE_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host


def commons_image(url):
    """A direct image address for a Wikimedia Commons file page."""
    match = re.search(r"commons\.wikimedia\.org/wiki/File:(.+)$", url)
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{match.group(1)}?width=640" if match else None


def year(date):
    return (date or "")[:4]


def release_section(group):
    secondary = group.get("secondary-types") or []
    if "Live" in secondary:
        return "Live"
    if "Compilation" in secondary:
        return "Compilations"
    if secondary:
        return "Other"
    return {"Album": "Albums", "EP": "EPs", "Single": "Singles"}.get(group.get("primary-type"), "Other")


def merge_person(people, person):
    """MusicBrainz lists one entry per role or period; show each person once."""
    for existing in people:
        if existing["mbid"] == person["mbid"]:
            existing["roles"] += [r for r in person["roles"] if r not in existing["roles"]]
            if person["years"] not in existing["years"].split(", "):
                existing["years"] += ", " + person["years"]
            existing["original"] |= person["original"]
            existing["current"] |= person["current"]
            return
    people.append(person)


def artist_profile(artist):
    """Everything the artist page shows, grouped into sections."""
    data = artist.data
    span = data.get("life-span") or {}

    links, image, related = {}, None, {}
    members, member_of = [], []
    for rel in data.get("relations", []):
        if rel.get("target-type") == "url":
            url = rel["url"]["resource"]
            if rel["type"] == "image":
                image = image or commons_image(url)
                continue
            group = next((label for label, types in LINK_GROUPS if rel["type"] in types), "Reference")
            links.setdefault(group, []).append({"url": url, "label": site_name(url), "kind": rel["type"]})
        elif rel.get("target-type") == "artist":
            person = {
                "name": rel["artist"]["name"],
                "mbid": rel["artist"]["id"],
                "years": "–".join(filter(None, [year(rel.get("begin")), year(rel.get("end")) or ("now" if not rel.get("ended") else "")])),
                "roles": [a for a in rel.get("attributes", []) if a not in ("original",)],
                "original": "original" in rel.get("attributes", []),
                "current": not rel.get("ended"),
            }
            if rel["type"] == "member of band":
                merge_person(members if rel.get("direction") == "backward" else member_of, person)
            else:
                related.setdefault(rel["type"].capitalize(), []).append(person)

    for group in links.values():
        unique = {link["url"]: link for link in group}  # the same address can be listed under two kinds
        group[:] = unique.values()

    sections = {label: [] for label in RELEASE_SECTIONS}
    for group in artist.release_groups:
        sections[release_section(group)].append({
            "title": group["title"],
            "year": year(group.get("first-release-date")),
            "mbid": group["id"],
            "cover": f"https://coverartarchive.org/release-group/{group['id']}/front-250",
        })
    discography = []
    for label, items in sections.items():
        if not items:
            continue
        if label in CAREER_ORDER:
            items.sort(key=lambda r: r["year"] or "9999")
        else:
            items.sort(key=lambda r: r["year"] or "0000", reverse=True)
        discography.append({"label": label, "total": len(items), "releases": items[:SHOW_PER_SECTION]})

    genres = [g["name"] for g in sorted(data.get("genres", []), key=lambda g: -g["count"])]
    tags = [t["name"] for t in sorted(data.get("tags", []), key=lambda t: -t["count"]) if t["name"] not in genres]
    rating = data.get("rating") or {}

    return {
        "name": data["name"],
        "mbid": str(artist.mbid),
        "disambiguation": data.get("disambiguation"),
        "type": data.get("type"),
        "gender": data.get("gender"),
        "origin": ", ".join(filter(None, [(data.get("begin-area") or {}).get("name"), (data.get("area") or {}).get("name")])),
        "active": "–".join(filter(None, [year(span.get("begin")), year(span.get("end")) or ("present" if not span.get("ended") else "")])),
        "ended": span.get("ended"),
        "rating": rating.get("value"),
        "rating_votes": rating.get("votes-count"),
        "genres": genres,
        "tags": tags[:12],
        "aliases": sorted({a["name"] for a in data.get("aliases", []) if a["name"] != data["name"]}),
        "image": image,
        "members": sorted(members, key=lambda m: (not m["current"], m["years"])),
        "member_of": member_of,
        "related": related,
        "discography": discography,
        "release_count": len(artist.release_groups),
        "links": [{"label": label, "items": links[label]} for label, _ in LINK_GROUPS if label in links],
        # The header buttons: each listening site once, then the official site.
        "quick_links": list({link["label"]: link for link in links.get("Listen", [])}.values())[:4],
        "official_url": next((link["url"] for link in links.get("Official", []) if link["kind"] == "official homepage"), None),
        "isnis": data.get("isnis", []),
        "ipis": data.get("ipis", []),
        "musicbrainz_url": f"https://musicbrainz.org/artist/{artist.mbid}",
        "fetched_at": artist.fetched_at,
    }
