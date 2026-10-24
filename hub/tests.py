from datetime import datetime
from decimal import Decimal
from unittest import mock

import requests
from django.test import TestCase
from django.urls import reverse

from .models import Note, Task
from .modules import MODULES
from .modules.currency import CurrencyModule
from .modules.news import NewsModule
from .modules.radio import IHeartStation, RadioModule, Station, TritonStation
from .modules.weather import WeatherModule


class FakeWeatherClient:
    def find_place(self, name):
        if name == "Nowhere":
            return None
        return {"name": name, "country": "France", "latitude": 48.85, "longitude": 2.35}

    def forecast(self, latitude, longitude):
        return {
            "current": {"temperature_2m": 9.2, "apparent_temperature": 7.0, "wind_speed_10m": 12, "weather_code": 3},
            "daily": {
                "time": ["2026-10-24", "2026-10-25"],
                "weather_code": [0, 61],
                "temperature_2m_max": [14, 12],
                "temperature_2m_min": [6, 5],
            },
        }


class FakeNewsClient:
    def front_page(self, limit=20):
        return [
            {"objectID": "1", "title": "With link", "url": "https://example.com", "points": 10, "num_comments": 3, "author": "ann"},
            {"objectID": "2", "title": "Ask HN", "url": None, "points": 5, "num_comments": None, "author": "bob"},
        ]


class FakeCurrencyClient:
    def currencies(self):
        return {"USD": "United States Dollar", "EUR": "Euro"}

    def convert(self, amount, source, target):
        rate = Decimal("0.9")
        return {"rate": rate, "result": (amount * rate).quantize(Decimal("0.01")), "date": "2026-10-23"}


class BrokenClient:
    """Fails every call, like a service that is down."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise requests.ConnectionError("down")

        return fail


class LayoutTests(TestCase):
    def test_home_links_to_every_module(self):
        with mock.patch.object(RadioModule, "stations", [FakeStation("WEBN", fail=True)]):
            response = self.client.get(reverse("hub:home"))
        self.assertEqual(response.status_code, 200)
        for module in MODULES:
            self.assertContains(response, reverse(f"hub:{module.slug}"))

    def test_menu_marks_current_page(self):
        response = self.client.get(reverse("hub:todo"))
        self.assertContains(response, f'href="{reverse("hub:todo")}" aria-current="page"')


@mock.patch.object(WeatherModule, "client_class", FakeWeatherClient)
class WeatherTests(TestCase):
    def test_shows_current_weather_and_forecast(self):
        response = self.client.get(reverse("hub:weather"), {"city": "Paris"})
        self.assertContains(response, "Paris, France")
        self.assertContains(response, "9.2°C")
        self.assertContains(response, "Overcast")
        self.assertContains(response, "Light rain")

    def test_unknown_city(self):
        response = self.client.get(reverse("hub:weather"), {"city": "Nowhere"})
        self.assertContains(response, "No place found")

    def test_service_down(self):
        with mock.patch.object(WeatherModule, "client_class", BrokenClient):
            response = self.client.get(reverse("hub:weather"))
        self.assertContains(response, "did not respond")


@mock.patch.object(NewsModule, "client_class", FakeNewsClient)
class NewsTests(TestCase):
    def test_lists_stories(self):
        response = self.client.get(reverse("hub:news"))
        self.assertContains(response, "With link")
        self.assertContains(response, 'href="https://example.com"')

    def test_story_without_url_links_to_discussion(self):
        response = self.client.get(reverse("hub:news"))
        stories = response.context["stories"]
        self.assertEqual(stories[1]["url"], "https://news.ycombinator.com/item?id=2")
        self.assertEqual(stories[1]["comments"], 0)

    def test_service_down(self):
        with mock.patch.object(NewsModule, "client_class", BrokenClient):
            response = self.client.get(reverse("hub:news"))
        self.assertContains(response, "did not respond")


@mock.patch.object(CurrencyModule, "client_class", FakeCurrencyClient)
class CurrencyTests(TestCase):
    def test_converts(self):
        response = self.client.get(reverse("hub:currency"), {"amount": "100", "from": "USD", "to": "EUR"})
        self.assertContains(response, "90.00 EUR")

    def test_same_currency_needs_no_api_call(self):
        response = self.client.get(reverse("hub:currency"), {"amount": "5", "from": "EUR", "to": "EUR"})
        self.assertEqual(response.context["conversion"]["result"], Decimal("5"))

    def test_rejects_bad_amount(self):
        response = self.client.get(reverse("hub:currency"), {"amount": "abc", "from": "USD", "to": "EUR"})
        self.assertContains(response, "Enter a number")

    def test_rejects_unknown_currency(self):
        response = self.client.get(reverse("hub:currency"), {"amount": "1", "from": "USD", "to": "XXX"})
        self.assertContains(response, "Choose currencies from the list")

    def test_service_down(self):
        with mock.patch.object(CurrencyModule, "client_class", BrokenClient):
            response = self.client.get(reverse("hub:currency"))
        self.assertContains(response, "did not respond")


class TodoTests(TestCase):
    url = reverse("hub:todo")

    def test_add_task(self):
        response = self.client.post(self.url, {"action": "add", "title": "Buy milk"})
        self.assertRedirects(response, self.url)
        self.assertTrue(Task.objects.filter(title="Buy milk").exists())

    def test_empty_title_shows_error(self):
        response = self.client.post(self.url, {"action": "add", "title": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(Task.objects.exists())

    def test_toggle_task(self):
        task = Task.objects.create(title="Walk")
        self.client.post(self.url, {"action": "toggle", "task": task.pk})
        task.refresh_from_db()
        self.assertTrue(task.done)

    def test_delete_task(self):
        task = Task.objects.create(title="Walk")
        self.client.post(self.url, {"action": "delete", "task": task.pk})
        self.assertFalse(Task.objects.exists())

    def test_missing_task_is_404(self):
        response = self.client.post(self.url, {"action": "toggle", "task": 999})
        self.assertEqual(response.status_code, 404)


class NotesTests(TestCase):
    url = reverse("hub:notes")

    def test_create_note(self):
        response = self.client.post(self.url, {"action": "save", "title": "Idea", "body": "Text"})
        note = Note.objects.get()
        self.assertRedirects(response, f"{self.url}?note={note.pk}")

    def test_edit_note(self):
        note = Note.objects.create(title="Old")
        self.client.post(self.url, {"action": "save", "note": note.pk, "title": "New", "body": ""})
        note.refresh_from_db()
        self.assertEqual(note.title, "New")
        self.assertEqual(Note.objects.count(), 1)

    def test_delete_note(self):
        note = Note.objects.create(title="Gone")
        self.client.post(self.url, {"action": "delete", "note": note.pk})
        self.assertFalse(Note.objects.exists())

    def test_open_note_fills_form(self):
        note = Note.objects.create(title="Shown", body="Body text")
        response = self.client.get(self.url, {"note": note.pk})
        self.assertContains(response, "Edit note")
        self.assertContains(response, "Body text")


class FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json, self.content = json_data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


TRITON_XML = b"""<?xml version="1.0" encoding="UTF-8"?><nowplaying-info-list>
<nowplaying-info type="track"><property name="cue_time_start"><![CDATA[2000000000000]]></property><property name="cue_time_duration"><![CDATA[200000]]></property><property name="cue_title"><![CDATA[Animal** ]]></property><property name="track_artist_name"><![CDATA[Katseye]]></property><property name="track_id"><![CDATA[2]]></property></nowplaying-info>
<nowplaying-info type="track"><property name="cue_time_start"><![CDATA[1000000300000]]></property><property name="cue_time_duration"><![CDATA[200000]]></property><property name="cue_title"><![CDATA[Umbrella]]></property><property name="track_artist_name"><![CDATA[Rihanna]]></property><property name="track_id"><![CDATA[1]]></property></nowplaying-info>
<nowplaying-info type="track"><property name="cue_time_start"><![CDATA[1000000000000]]></property><property name="cue_time_duration"><![CDATA[200000]]></property><property name="cue_title"><![CDATA[Umbrella]]></property><property name="track_artist_name"><![CDATA[Rihanna]]></property><property name="track_id"><![CDATA[1]]></property></nowplaying-info>
</nowplaying-info-list>"""


class FakeStation(Station):
    def __init__(self, name, tracks=None, fail=False):
        self.name, self.frequency, self._tracks, self.fail = name, "1 FM", tracks or [], fail

    def tracks(self, limit=10):
        if self.fail:
            raise requests.ConnectionError("down")
        return [dict(track) for track in self._tracks[:limit]]


def song(title, artist, end):
    return {"title": title, "artist": artist, "image": "", "played_at": datetime(2026, 10, 24, 0, 21), "end": end}


class StationTests(TestCase):
    def test_iheart_maps_history_and_uses_https_images(self):
        data = {"data": [{"title": "Self Esteem", "artist": "The Offspring", "startTime": 100, "endTime": 9999999999, "imagePath": "http://image.iheart.com/a.jpg"}]}
        with mock.patch("hub.modules.radio.requests.get", return_value=FakeResponse(data)):
            tracks = IHeartStation("WEBN", "102.7 FM", 1701).recent()
        self.assertEqual(tracks[0]["title"], "Self Esteem")
        self.assertEqual(tracks[0]["image"], "https://image.iheart.com/a.jpg")
        self.assertTrue(tracks[0]["playing"])

    def test_triton_merges_repeated_cues_and_strips_titles(self):
        with mock.patch("hub.modules.radio.requests.get", return_value=FakeResponse(content=TRITON_XML)):
            tracks = TritonStation("WKRQ", "101.9 FM", "WKRQFM").recent()
        self.assertEqual([t["title"] for t in tracks], ["Animal", "Umbrella"])
        # The repeated Umbrella cue keeps the earlier start time.
        self.assertEqual(tracks[1]["played_at"].timestamp(), 1000000000)
        self.assertFalse(tracks[1]["playing"])

    def test_only_the_newest_unfinished_song_is_playing(self):
        station = FakeStation("X", [song("New", "A", 9999999999), song("Old", "B", 9999999999)])
        self.assertEqual([t["playing"] for t in station.recent()], [True, False])

    def test_finished_newest_song_is_last_played(self):
        station = FakeStation("X", [song("Done", "A", 0)])
        self.assertFalse(station.recent()[0]["playing"])


class RadioTests(TestCase):
    stations = [
        FakeStation("WEBN", [song("Self Esteem", "The Offspring", 9999999999), song("Simple Man", "Lynyrd Skynyrd", 0)]),
        FakeStation("WKRQ", fail=True),
    ]

    def test_home_card_shows_each_station_current_song(self):
        with mock.patch.object(RadioModule, "stations", self.stations):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, "WEBN · Now playing")
        self.assertContains(response, "Self Esteem")
        self.assertNotContains(response, "Simple Man")
        self.assertContains(response, "WKRQ · Unavailable")

    def test_other_cards_still_show_their_summary(self):
        with mock.patch.object(RadioModule, "stations", self.stations):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, WeatherModule.summary)

    def test_page_lists_recent_songs_and_reports_a_failed_station(self):
        with mock.patch.object(RadioModule, "stations", self.stations):
            response = self.client.get(reverse("hub:radio"))
        self.assertContains(response, "Simple Man")
        self.assertContains(response, "12:21 AM")
        self.assertContains(response, "Song information is not available right now.")


class LiveRadioTests(TestCase):
    @staticmethod
    async def open_socket(origin):
        """Open /ws/radio/ through the real ASGI app. Returns (communicator, accepted)."""
        from asgiref.testing import ApplicationCommunicator

        from config.asgi import application

        scope = {
            "type": "websocket",
            "path": "/ws/radio/",
            "headers": [(b"host", b"localhost"), (b"origin", origin)],
            "query_string": b"",
            "subprotocols": [],
        }
        communicator = ApplicationCommunicator(application, scope)
        await communicator.send_input({"type": "websocket.connect"})
        reply = await communicator.receive_output(timeout=2)
        return communicator, reply["type"] == "websocket.accept"

    def test_websocket_receives_broadcasts(self):
        import json

        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        async def scenario():
            communicator, accepted = await self.open_socket(b"http://localhost")
            self.assertTrue(accepted)
            await get_channel_layer().group_send("radio", {"type": "radio.update", "html": "<ul>new</ul>"})
            message = await communicator.receive_output(timeout=2)
            self.assertEqual(json.loads(message["text"]), {"html": "<ul>new</ul>"})
            await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
            await communicator.wait(timeout=2)

        async_to_sync(scenario)()

    def test_websocket_rejects_other_sites(self):
        from asgiref.sync import async_to_sync

        async def scenario():
            _, accepted = await self.open_socket(b"http://evil.example")
            self.assertFalse(accepted)

        async_to_sync(scenario)()

    def test_listener_broadcasts_only_when_a_song_changes(self):
        from hub.listener import RadioListener

        station = FakeStation("WEBN", [song("Self Esteem", "The Offspring", 9999999999)])
        listener = RadioListener()
        with mock.patch.object(RadioModule, "stations", [station]), \
                mock.patch("hub.listener.get_channel_layer") as layer:
            layer.return_value.group_send = mock.AsyncMock()

            self.assertTrue(listener.check())  # first check always broadcasts
            self.assertFalse(listener.check())  # same song: nothing to send

            station._tracks = [song("Simple Man", "Lynyrd Skynyrd", 9999999999)]
            self.assertTrue(listener.check())

        sent = layer.return_value.group_send.await_args_list
        self.assertEqual(len(sent), 2)
        group, message = sent[1].args
        self.assertEqual(group, "radio")
        self.assertIn("Simple Man", message["html"])
        self.assertIn('data-live-card="radio"', message["html"])

    def test_listener_retries_after_a_failed_broadcast(self):
        from hub.listener import RadioListener

        station = FakeStation("WEBN", [song("Self Esteem", "The Offspring", 9999999999)])
        listener = RadioListener()
        with mock.patch.object(RadioModule, "stations", [station]), \
                mock.patch("hub.listener.get_channel_layer") as layer:
            layer.return_value.group_send = mock.AsyncMock(side_effect=[ConnectionError("Redis is down"), None])
            with self.assertRaises(ConnectionError):
                listener.check()
            self.assertTrue(listener.check())  # same song, sent again
        self.assertEqual(layer.return_value.group_send.await_count, 2)

    def test_listener_broadcasts_when_a_song_ends(self):
        from hub.listener import RadioListener

        station = FakeStation("WEBN", [song("Self Esteem", "The Offspring", 9999999999)])
        listener = RadioListener()
        with mock.patch.object(RadioModule, "stations", [station]), \
                mock.patch("hub.listener.get_channel_layer") as layer:
            layer.return_value.group_send = mock.AsyncMock()
            listener.check()
            station._tracks = [song("Self Esteem", "The Offspring", 0)]  # same song, now finished
            self.assertTrue(listener.check())
        self.assertIn("Last played", layer.return_value.group_send.await_args.args[1]["html"])

    def test_home_page_loads_the_live_script(self):
        with mock.patch.object(RadioModule, "stations", [FakeStation("WEBN", fail=True)]):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, "hub/live.js")
        self.assertContains(response, 'data-live-card="radio"')
