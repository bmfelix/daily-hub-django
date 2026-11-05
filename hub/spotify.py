"""The site owner's Spotify listening. Needs a Spotify developer app and one login, then renews itself."""

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import SpotifyAccount

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-currently-playing user-read-recently-played user-top-read"
CACHE_KEY = "spotify-listening"
CACHE_SECONDS = 20  # the homepage asks every 30 seconds, for every open page
TOP_CACHE_SECONDS = 60 * 60
TOP_SHOWN = 10


def is_configured():
    return bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET)


def playlist_embed_urls():
    """A Spotify player address for each playlist link in SPOTIFY_PLAYLIST_URL (comma separated)."""
    ids = re.findall(r"playlist[/:]([A-Za-z0-9]+)", settings.SPOTIFY_PLAYLIST_URL)
    return [f"https://open.spotify.com/embed/playlist/{playlist}?theme=0" for playlist in ids]


def track_details(track, playing, played_at=None):
    images = (track.get("album") or {}).get("images") or []
    artists = [artist["name"] for artist in track.get("artists", [])]
    return {
        "title": track["name"],
        "artist": ", ".join(artists),
        "first_artist": artists[0] if artists else "",
        "album": (track.get("album") or {}).get("name", ""),
        "artwork": images[0]["url"] if images else "",
        "url": (track.get("external_urls") or {}).get("spotify", ""),
        "playing": playing,
        "played_at": played_at,
    }


class SpotifyClient:
    timeout = 8

    def authorize_url(self, state):
        return f"{AUTHORIZE_URL}?" + urlencode({
            "client_id": settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        })

    def _token(self, **data):
        response = requests.post(
            TOKEN_URL, data=data, timeout=self.timeout,
            auth=(settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET),
        )
        response.raise_for_status()
        return response.json()

    def exchange_code(self, code):
        return self._token(grant_type="authorization_code", code=code, redirect_uri=settings.SPOTIFY_REDIRECT_URI)

    def refresh(self, refresh_token):
        return self._token(grant_type="refresh_token", refresh_token=refresh_token)

    def _get(self, token, path, **params):
        response = requests.get(
            f"{API_URL}/{path}", params=params, timeout=self.timeout, headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json() if response.status_code != 204 else None  # 204: nothing is playing

    def top(self, token, kind, time_range):
        return self._get(token, f"me/top/{kind}", time_range=time_range, limit=TOP_SHOWN).get("items", [])

    def currently_playing(self, token):
        data = self._get(token, "me/player/currently-playing")
        if not data or not data.get("is_playing") or not data.get("item"):
            return None
        return track_details(data["item"], playing=True)

    def last_played(self, token):
        items = self._get(token, "me/player/recently-played", limit=1).get("items") or []
        if not items:
            return None
        return track_details(items[0]["track"], playing=False, played_at=datetime.fromisoformat(items[0]["played_at"]))


def save_tokens(account, tokens):
    account.access_token = tokens["access_token"]
    # Spotify may or may not send a new refresh token; keep the old one if not.
    account.refresh_token = tokens.get("refresh_token") or account.refresh_token
    account.expires_at = timezone.now() + timedelta(seconds=tokens["expires_in"] - 60)
    account.save()


def fresh_token(account, client):
    if timezone.now() >= account.expires_at:
        save_tokens(account, client.refresh(account.refresh_token))
    return account.access_token


def listening(client=None):
    """What is playing now, or else what played last. None if not connected."""
    account = SpotifyAccount.objects.first()
    if account is None:
        return None
    details = cache.get(CACHE_KEY)
    if details is None:
        client = client or SpotifyClient()
        token = fresh_token(account, client)
        details = client.currently_playing(token) or client.last_played(token)
        cache.set(CACHE_KEY, details, CACHE_SECONDS)
    return details


def artist_details(artist):
    images = artist.get("images") or []
    return {
        "name": artist["name"],
        "image": images[-2]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
        "genres": artist.get("genres", [])[:3],
        "url": (artist.get("external_urls") or {}).get("spotify", ""),
    }


def top_items(time_range, client=None):
    """Top tracks and artists for a period. None if not connected."""
    account = SpotifyAccount.objects.first()
    if account is None:
        return None
    key = f"spotify-top-{time_range}"
    stats = cache.get(key)
    if stats is None:
        client = client or SpotifyClient()
        token = fresh_token(account, client)
        stats = {
            "tracks": [track_details(track, playing=False) for track in client.top(token, "tracks", time_range)],
            "artists": [artist_details(artist) for artist in client.top(token, "artists", time_range)],
        }
        cache.set(key, stats, TOP_CACHE_SECONDS)
    return stats
