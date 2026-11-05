import time
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from ..models import Play, Song
from ..names import song_key
from .base import HubModule

IHEART_HISTORY_URL = "https://us.api.iheart.com/api/v3/live-meta/stream/{station}/trackHistory"
TRITON_NOW_PLAYING_URL = "https://np.tritondigital.com/public/nowplaying"
CINCINNATI = ZoneInfo("America/New_York")
TIMEOUT = 5


def make_track(title, artist, start, end, image=""):
    return {
        "title": title.strip(),
        "artist": artist.strip(),
        "image": image,
        "played_at": datetime.fromtimestamp(start, CINCINNATI),
        "end": end,
    }


class Station:
    """One radio station. Subclasses read song data from their broadcaster's API."""

    name = ""
    frequency = ""
    stream_url = ""  # the station's live audio

    def tracks(self, limit=10):
        """Return recent songs, newest first. Each subclass calls its own API here."""
        raise NotImplementedError

    def recent(self, limit=10):
        """Recent songs, newest first. The newest is marked as playing if it has not ended yet."""
        tracks = self.tracks(limit)
        now = time.time()
        for i, track in enumerate(tracks):
            track["playing"] = i == 0 and now < track["end"]
        return tracks


class IHeartStation(Station):
    """Reads song history from iHeartRadio's public API (no key). The newest song can appear about a minute late."""

    def __init__(self, name, frequency, station_id):
        self.name, self.frequency, self.station_id = name, frequency, station_id
        self.stream_url = f"https://stream.revma.ihrhls.com/zc{station_id}"

    def tracks(self, limit=10):
        response = requests.get(
            IHEART_HISTORY_URL.format(station=self.station_id), params={"limit": limit}, timeout=TIMEOUT
        )
        response.raise_for_status()
        return [
            make_track(
                item["title"],
                item["artist"],
                item["startTime"],
                item["endTime"],
                (item.get("imagePath") or "").replace("http://", "https://", 1),
            )
            for item in response.json()["data"]
        ]


class TritonStation(Station):
    """Reads live song data from Triton Digital's public now-playing feed (no key)."""

    def __init__(self, name, frequency, mount):
        self.name, self.frequency, self.mount = name, frequency, mount
        self.stream_url = f"https://playerservices.streamtheworld.com/api/livestream-redirect/{mount}.mp3"

    def tracks(self, limit=10):
        response = requests.get(
            TRITON_NOW_PLAYING_URL,
            # Ask for extra: the feed repeats a song when it is cued twice.
            params={"mountName": self.mount, "numberToFetch": limit * 2, "eventType": "track"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        tracks, last_id = [], None
        for event in ET.fromstring(response.content):
            props = {prop.get("name"): prop.text or "" for prop in event.findall("property")}
            start = int(props["cue_time_start"]) / 1000
            end = start + int(props.get("cue_time_duration") or 0) / 1000
            # The feed marks some titles with trailing asterisks, as in "Rolling In The Deep**".
            title = props.get("cue_title", "").strip().rstrip("*")
            track = make_track(title, props.get("track_artist_name", ""), start, end)
            if props.get("track_id") == last_id:
                tracks[-1] = track  # an older cue of the same song: keep its earlier start
            else:
                tracks.append(track)
            last_id = props.get("track_id")
        return tracks[:limit]


class RadioModule(HubModule):
    slug = "radio"
    title = "Radio"
    summary = "What is playing on Cincinnati radio."
    card_template = "hub/cards/radio.html"

    stations = [
        IHeartStation("WEBN", "102.7 FM", station_id=1701),
        TritonStation("WKRQ", "Q102 · 101.9 FM", mount="WKRQFM"),
    ]
    unavailable = "Song information is not available right now."

    @classmethod
    def station_data(cls, limit):
        results = []
        for station in cls.stations:
            try:
                results.append({"station": station, "tracks": station.recent(limit)})
            except (requests.RequestException, ET.ParseError, KeyError, ValueError):
                results.append({"station": station, "error": cls.unavailable})
        return results

    @classmethod
    def card(cls):
        return {"stations": cls.with_saved_songs(cls.station_data(limit=1))}

    def load(self):
        return {"stations": self.with_saved_songs(self.station_data(limit=10))}

    @staticmethod
    def with_saved_songs(stations):
        """Add each track's saved previews. The listener looks songs up, so pages stay fast."""
        tracks = [track for item in stations for track in item.get("tracks", [])]
        keys = {song_key(track["artist"], track["title"]) for track in tracks}
        songs = {song.key: song for song in Song.objects.filter(key__in=keys)}
        for track in tracks:
            track["song"] = songs.get(song_key(track["artist"], track["title"]))
        return stations

    @classmethod
    def remember_recent(cls):
        """Save every recent play for the charts, and return (artist, title) for each."""
        plays = [
            Play(
                station=item["station"].name, artist_name=track["artist"], title=track["title"],
                song_key=song_key(track["artist"], track["title"]), played_at=track["played_at"],
            )
            for item in cls.station_data(limit=10)
            for track in item.get("tracks", [])
            if track["artist"] and track["title"]
        ]
        Play.objects.bulk_create(plays, ignore_conflicts=True)  # plays already saved are skipped
        return [(play.artist_name, play.title) for play in plays]
