"""Song previews and album artwork from Apple and Deezer. Neither needs a key."""

import re
from datetime import timedelta

import requests
from django.utils import timezone

from .models import ArtistName, Song
from .names import compact, name_candidates, normalize, song_key

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DEEZER_SEARCH_URL = "https://api.deezer.com/search"
DEEZER_TRACK_URL = "https://api.deezer.com/track/{track_id}"

REFRESH_AFTER = timedelta(days=30)  # songs with a preview
RETRY_MISSING_AFTER = timedelta(days=7)  # songs without one


def same_artist(wanted, found):
    """True when a service's artist name matches, allowing for "A & B" on either side."""
    found = compact(found)
    return bool(found) and any(name and (name in found or found in name) for name in map(compact, name_candidates(wanted)))


def best_match(items, artist, title, read):
    """The item for this song: an exact title first, then one with extra words like "(Remastered)"."""
    wanted = compact(title)
    if not wanted:
        return None
    matches = []
    for item in items:
        found_artist, found_title = read(item)
        if same_artist(artist, found_artist):
            matches.append((compact(found_title), item))
    for found, item in matches:
        if found == wanted:
            return item
    for found, item in matches:
        if found and (found.startswith(wanted) or wanted.startswith(found)):
            return item
    return None


def album_key(title):
    """An album's title without extras, so "Ten (Remastered)" and "Ten - EP" match "Ten"."""
    return normalize(re.sub(r"\s*(?:[(\[].*|-\s*(?:Single|EP))$", "", title))


class MusicClient:
    """Talks to the iTunes Search API and the Deezer API."""

    timeout = 8

    def _get(self, url, **params):
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def apple_song(self, artist, title):
        results = self._get(
            ITUNES_SEARCH_URL, term=f"{artist} {title}", entity="song", limit=10, country="US",
        ).get("results", [])
        return best_match(results, artist, title, lambda item: (item.get("artistName", ""), item.get("trackName", "")))

    def deezer_song(self, artist, title):
        results = self._get(DEEZER_SEARCH_URL, q=f"{artist} {title}", limit=10).get("data", [])
        return best_match(
            results, artist, title, lambda item: ((item.get("artist") or {}).get("name", ""), item.get("title", "")),
        )

    def deezer_preview(self, track_id):
        """A preview address. Deezer's expire within minutes, so they are fetched when played, never saved."""
        return self._get(DEEZER_TRACK_URL.format(track_id=track_id)).get("preview", "")

    def apple_albums(self, artist):
        """Every Apple album by this exact artist, as {album key: {artwork, url}}."""
        results = self._get(
            ITUNES_SEARCH_URL, term=artist, entity="album", attribute="artistTerm", limit=200, country="US",
        ).get("results", [])
        albums = {}
        for item in results:
            if compact(item.get("artistName", "")) != compact(artist) or not item.get("artworkUrl100"):
                continue
            albums.setdefault(album_key(item.get("collectionName", "")), {
                "artwork": item["artworkUrl100"].replace("100x100bb", "250x250bb"),
                "url": item.get("collectionViewUrl", ""),
            })
        return albums


class SongLibrary:
    """Finds a song's previews once and saves them. Apple comes first, then Deezer."""

    def __init__(self, client=None):
        self.client = client or MusicClient()

    def find(self, artist, title):
        song = Song.objects.filter(key=song_key(artist, title)).first()
        if song and not self.is_stale(song):
            return song
        return self.look_up(song or Song(artist_name=artist.strip(), title=title.strip()))

    @staticmethod
    def is_stale(song):
        if song.locked:
            return False
        wait = REFRESH_AFTER if song.has_preview else RETRY_MISSING_AFTER
        return song.checked_at is None or timezone.now() - song.checked_at >= wait

    def look_up(self, song):
        apple = self.client.apple_song(song.artist_name, song.title) or {}
        deezer = {}
        if not apple.get("previewUrl"):
            deezer = self.client.deezer_song(song.artist_name, song.title) or {}

        song.apple_preview_url = apple.get("previewUrl", "")
        song.apple_url = apple.get("trackViewUrl", "")
        song.deezer_track_id = deezer.get("id")
        song.deezer_url = deezer.get("link", "")
        song.album = apple.get("collectionName") or (deezer.get("album") or {}).get("title", "")
        song.artwork_url = (apple.get("artworkUrl100") or "").replace("100x100bb", "250x250bb") or (
            (deezer.get("album") or {}).get("cover_medium", "")
        )
        entry = ArtistName.objects.select_related("artist").filter(key=song.artist_name.strip().lower()).first()
        if entry and entry.artist:
            song.artist = entry.artist
        song.checked_at = timezone.now()
        song.save()
        return song
