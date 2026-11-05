from datetime import datetime, timedelta

import icalendar
import recurring_ical_events
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .base import HubModule

DAYS_AHEAD = 14
CACHE_KEY = "agenda-events"
CACHE_SECONDS = 15 * 60


class CalendarClient:
    """Reads calendars from their iCal addresses, which is how Apple Calendar shares them."""

    timeout = 10

    def events(self, url, start, end):
        response = requests.get(url.strip().replace("webcal://", "https://", 1), timeout=self.timeout)
        response.raise_for_status()
        calendar = icalendar.Calendar.from_ical(response.content)
        return recurring_ical_events.of(calendar).between(start, end)


def agenda_item(event):
    start = event["DTSTART"].dt
    all_day = not isinstance(start, datetime)
    if not all_day and timezone.is_aware(start):
        start = timezone.localtime(start)
    return {
        "title": str(event.get("SUMMARY", "Untitled")),
        "location": str(event.get("LOCATION", "")),
        "all_day": all_day,
        "day": start if all_day else start.date(),
        "time": None if all_day else start.time(),
    }


class AgendaModule(HubModule):
    """Private: only the logged-in owner can see it."""

    slug = "agenda"
    title = "Agenda"
    summary = "What is on your calendars for the next two weeks."
    live_card = True
    staff_only = True
    client_class = CalendarClient

    def fetch(self):
        """All events and how many calendars could not be read. One bad calendar does not hide the rest."""
        client = self.client_class()
        today = timezone.localdate()
        items, failed = [], 0
        for url in settings.CALENDAR_URLS:
            try:
                items += [agenda_item(event) for event in client.events(url, today, today + timedelta(days=DAYS_AHEAD))]
            except (requests.RequestException, ValueError, KeyError):
                failed += 1
        items.sort(key=lambda item: (item["day"], not item["all_day"], str(item["time"])))
        return items, failed

    def load(self):
        if not settings.CALENDAR_URLS:
            return {"error": "Add your calendar links to see them here."}
        cached = cache.get(CACHE_KEY)
        if cached is None:
            cached = self.fetch()
            if not cached[1]:
                cache.set(CACHE_KEY, cached, CACHE_SECONDS)
        items, failed = cached
        days = {}
        for item in items:
            days.setdefault(item["day"], []).append(item)
        return {
            "items": items,
            "days": [{"date": day, "items": entries} for day, entries in days.items()],
            "failed": failed,
        }
