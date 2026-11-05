from datetime import date, datetime, time, timedelta

from django.db.models import Count, Min
from django.utils import timezone

from ..models import Play, Song
from .base import HubModule

CHART_SIZE = 10


def monday_of(day):
    return day - timedelta(days=day.weekday())


def week_range(monday):
    """The start and end of a week, as moments in the site's time zone."""
    start = timezone.make_aware(datetime.combine(monday, time.min))
    return start, timezone.make_aware(datetime.combine(monday + timedelta(days=7), time.min))


def with_bars(rows):
    """Add how long each row's bar is, compared to the top of the chart."""
    top = rows[0]["plays"] if rows else 1
    return [{**row, "bar": round(row["plays"] / top * 100)} for row in rows]


def top_songs(plays, limit=CHART_SIZE):
    rows = list(
        plays.values("song_key").annotate(count=Count("id"), name=Min("title"), artist=Min("artist_name"))
        .order_by("-count", "name")[:limit]
    )
    songs = {song.key: song for song in Song.objects.filter(key__in=[row["song_key"] for row in rows])}
    return with_bars([
        {"title": row["name"], "artist": row["artist"], "plays": row["count"], "song": songs.get(row["song_key"])}
        for row in rows
    ])


def top_artists(plays, limit=CHART_SIZE):
    rows = plays.values("artist_name").annotate(count=Count("id")).order_by("-count", "artist_name")[:limit]
    return with_bars([{"artist": row["artist_name"], "plays": row["count"]} for row in rows])


class ChartsModule(HubModule):
    slug = "charts"
    title = "Charts"
    summary = "The most-played songs and artists on Cincinnati radio, week by week."
    card_template = "hub/cards/charts.html"

    @classmethod
    def card(cls):
        start, end = week_range(monday_of(timezone.localdate()))
        plays = Play.objects.filter(played_at__gte=start, played_at__lt=end)
        return {"songs": top_songs(plays, limit=3), "total": plays.count()}

    def chosen_week(self):
        try:
            return monday_of(date.fromisoformat(self.request.GET.get("week", "")))
        except ValueError:
            return monday_of(timezone.localdate())

    def load(self):
        monday = self.chosen_week()
        start, end = week_range(monday)
        plays = Play.objects.filter(played_at__gte=start, played_at__lt=end)
        stations = sorted(set(plays.values_list("station", flat=True)))
        this_week = monday_of(timezone.localdate())
        first_play = Play.objects.order_by("played_at").first()
        return {
            "monday": monday,
            "sunday": monday + timedelta(days=6),
            "previous_week": monday - timedelta(days=7) if first_play and start > first_play.played_at else None,
            "next_week": monday + timedelta(days=7) if monday < this_week else None,
            "total": plays.count(),
            "stations": [
                {
                    "name": name,
                    "songs": top_songs(plays.filter(station=name)),
                    "artists": top_artists(plays.filter(station=name)),
                }
                for name in stations
            ],
        }
