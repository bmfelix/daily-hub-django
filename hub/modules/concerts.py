from datetime import date

import requests
from django.conf import settings
from django.core.cache import cache

from .base import HubModule

EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
CITIES = [("Cincinnati", "OH"), ("Dayton", "OH"), ("Columbus", "OH")]
CACHE_SECONDS = 6 * 60 * 60  # listings change slowly, and the free key has a daily limit


class TicketmasterClient:
    """Talks to Ticketmaster's Discovery API. Needs a free key in TICKETMASTER_API_KEY."""

    timeout = 8

    def events(self, city, state, size=30):
        response = requests.get(EVENTS_URL, timeout=self.timeout, params={
            "apikey": settings.TICKETMASTER_API_KEY,
            "classificationName": "music",
            "city": city,
            "stateCode": state,
            "sort": "date,asc",
            "size": size,
        })
        response.raise_for_status()
        return response.json().get("_embedded", {}).get("events", [])


def concert(event, city):
    """The parts of a Ticketmaster event the page shows."""
    start = event.get("dates", {}).get("start", {})
    venues = event.get("_embedded", {}).get("venues") or [{}]
    images = sorted(event.get("images") or [], key=lambda image: image.get("width", 0))
    medium = next((image for image in images if image.get("width", 0) >= 300), images[-1] if images else {})
    return {
        "name": event.get("name", ""),
        "url": event.get("url", ""),
        "date": date.fromisoformat(start["localDate"]) if start.get("localDate") else None,
        "time": start.get("localTime", ""),
        "venue": venues[0].get("name", ""),
        "city": city,
        "image": medium.get("url", ""),
        "artists": [artist["name"] for artist in event.get("_embedded", {}).get("attractions", []) if artist.get("name")],
    }


class ConcertsModule(HubModule):
    slug = "concerts"
    title = "Concerts"
    summary = "Upcoming shows in Cincinnati, Dayton, and Columbus."
    live_card = True
    client_class = TicketmasterClient
    cities = CITIES

    def city_events(self, client, city, state):
        key = f"concerts-{city}"
        events = cache.get(key)
        if events is None:
            events = [concert(event, city) for event in client.events(city, state)]
            cache.set(key, events, CACHE_SECONDS)
        return events

    def load(self):
        names = [city for city, _ in self.cities]
        chosen = self.request.GET.get("city", "")
        context = {"cities": names, "chosen": chosen if chosen in names else ""}
        if not settings.TICKETMASTER_API_KEY:
            return {**context, "error": "Concert listings need a Ticketmaster API key."}

        client = self.client_class()
        concerts = []
        for city, state in self.cities:
            if context["chosen"] in ("", city):
                try:
                    concerts += self.city_events(client, city, state)
                except requests.RequestException:
                    return {**context, "error": "The concert service did not respond. Try again shortly."}
        concerts = [show for show in concerts if show["date"]]
        return {**context, "concerts": sorted(concerts, key=lambda show: (show["date"], show["time"]))}
