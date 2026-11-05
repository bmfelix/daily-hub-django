import requests

from .. import spotify
from .base import HubModule

RANGES = {"short_term": "Last 4 weeks", "medium_term": "Last 6 months", "long_term": "All time"}


class ListeningModule(HubModule):
    slug = "listening"
    title = "Listening"
    summary = "Top artists and tracks from Spotify."
    on_home = False

    def load(self):
        chosen = self.request.GET.get("range")
        chosen = chosen if chosen in RANGES else "short_term"
        context = {"ranges": RANGES.items(), "chosen": chosen}
        try:
            stats = spotify.top_items(chosen)
        except requests.RequestException:
            return {**context, "error": "Spotify did not respond. Try again shortly."}
        if stats is None:
            return {**context, "error": "Connect Spotify from the homepage to see listening stats."}
        return {**context, **stats}
