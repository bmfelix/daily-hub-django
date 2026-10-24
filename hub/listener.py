from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.template.loader import render_to_string

from .consumers import RADIO_GROUP
from .modules.radio import RadioModule


class RadioListener:
    """Checks the stations and broadcasts the Radio card when a song changes.

    The station feeds cannot be subscribed to, so the listener asks on a timer.
    """

    def __init__(self):
        self.last_seen = None

    @staticmethod
    def signature(card):
        """What a viewer can see change: each station's song and whether it is still playing."""
        result = []
        for item in card["stations"]:
            track = (item.get("tracks") or [None])[0]
            result.append((item["station"].name, track and (track["title"], track["artist"], track["playing"])))
        return tuple(result)

    def check(self):
        """Broadcast if anything changed since the last check. Returns True when it broadcast."""
        card = RadioModule.card()
        seen = self.signature(card)
        if seen == self.last_seen:
            return False
        html = render_to_string(RadioModule.card_template, {"card": card})
        async_to_sync(get_channel_layer().group_send)(RADIO_GROUP, {"type": "radio.update", "html": html})
        # Remember only after a successful send, so a failed broadcast is retried.
        self.last_seen = seen
        return True
