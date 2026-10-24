import json

from channels.generic.websocket import AsyncWebsocketConsumer

RADIO_GROUP = "radio"


class RadioConsumer(AsyncWebsocketConsumer):
    """One browser tab watching the Radio card. The listener worker broadcasts to the group."""

    async def connect(self):
        await self.channel_layer.group_add(RADIO_GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(RADIO_GROUP, self.channel_name)

    async def radio_update(self, event):
        await self.send(text_data=json.dumps({"html": event["html"]}))
