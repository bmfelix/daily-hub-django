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


PEARL_JAM_ID = "83b9cbe7-9857-49e2-ab8e-b57b01038103"
VEDDER_ID = "8b9d3d7f-3a37-4e8f-b9e8-0e3b6a4f1c2d"

PEARL_JAM = {
    "id": PEARL_JAM_ID, "name": "Pearl Jam", "type": "Group", "country": "US",
    "area": {"name": "United States"}, "begin-area": {"name": "Seattle"},
    "life-span": {"begin": "1990", "end": None, "ended": False},
    "aliases": [{"name": "Mookie Blaylock"}], "isnis": ["0000000123426109"], "ipis": [],
    "genres": [{"name": "rock", "count": 5}, {"name": "grunge", "count": 9}],
    "tags": [{"name": "grunge", "count": 9}, {"name": "seattle", "count": 3}],
    "rating": {"value": 4.6, "votes-count": 29},
    "relations": [
        {"target-type": "url", "type": "official homepage", "url": {"resource": "https://pearljam.com/"}},
        {"target-type": "url", "type": "free streaming", "url": {"resource": "https://open.spotify.com/artist/1w5K"}},
        {"target-type": "url", "type": "image", "url": {"resource": "https://commons.wikimedia.org/wiki/File:PJ.jpg"}},
        {"target-type": "artist", "type": "member of band", "direction": "backward", "begin": "1990", "ended": False,
         "attributes": ["original", "lead vocals"], "artist": {"id": VEDDER_ID, "name": "Eddie Vedder"}},
        {"target-type": "artist", "type": "member of band", "direction": "backward", "begin": "1990-09-22",
         "end": "1991-05-22", "ended": True, "attributes": ["drums"], "artist": {"id": "11111111-1111-1111-1111-111111111111", "name": "Dave Krusen"}},
    ],
}

RELEASE_GROUPS = [
    {"id": "aaaaaaaa-0000-0000-0000-000000000001", "title": "Vs.", "primary-type": "Album", "first-release-date": "1993-10-08"},
    {"id": "aaaaaaaa-0000-0000-0000-000000000002", "title": "Ten", "primary-type": "Album", "first-release-date": "1991-08-27"},
    {"id": "aaaaaaaa-0000-0000-0000-000000000003", "title": "Alive", "primary-type": "Single", "first-release-date": "1991"},
    {"id": "aaaaaaaa-0000-0000-0000-000000000004", "title": "Live on Two Legs", "primary-type": "Album",
     "secondary-types": ["Live"], "first-release-date": "1998"},
]


class FakeMusicBrainz:
    """Stands in for MusicBrainzClient and counts the calls."""

    def __init__(self):
        self.calls = []

    def search_artists(self, name, limit=5):
        self.calls.append(("search", name))
        known = {"pearl jam": PEARL_JAM_ID, "tame impala": "22222222-2222-2222-2222-222222222222"}
        mbid = known.get(name.lower())
        return [{"id": mbid, "name": name, "score": 100}] if mbid else [{"id": "x", "name": "Something Else", "score": 95}]

    def artist(self, mbid):
        self.calls.append(("artist", mbid))
        if mbid == PEARL_JAM_ID:
            return PEARL_JAM
        return {"id": mbid, "name": "Tame Impala" if mbid.startswith("2222") else "Eddie Vedder", "relations": []}

    def release_groups(self, mbid, pages=15):
        self.calls.append(("release_groups", mbid))
        return RELEASE_GROUPS if mbid == PEARL_JAM_ID else []


class ArtistLibraryTests(TestCase):
    def setUp(self):
        from hub.musicbrainz import ArtistLibrary

        self.client_mb = FakeMusicBrainz()
        self.library = ArtistLibrary(self.client_mb)

    def test_first_lookup_fetches_and_saves_everything(self):
        from hub.models import Artist

        artist = self.library.find("Pearl Jam")
        self.assertEqual(artist.name, "Pearl Jam")
        saved = Artist.objects.get(mbid=PEARL_JAM_ID)
        self.assertEqual(saved.data["rating"]["value"], 4.6)
        self.assertEqual(len(saved.release_groups), 4)
        self.assertEqual([c[0] for c in self.client_mb.calls], ["search", "artist", "release_groups"])

    def test_second_lookup_uses_the_database_only(self):
        self.library.find("Pearl Jam")
        calls = len(self.client_mb.calls)
        self.library.find("  pearl jam ")  # same name, different spacing and case
        self.assertEqual(len(self.client_mb.calls), calls)

    def test_combined_names_fall_back_to_the_first_artist(self):
        artist = self.library.find("Tame Impala [+] Jennie")
        self.assertEqual(artist.name, "Tame Impala")
        self.assertEqual(self.client_mb.calls[:2], [("search", "Tame Impala [+] Jennie"), ("search", "Tame Impala")])

    def test_a_close_but_different_name_is_not_a_match(self):
        self.assertIsNone(self.library.find("Unknown Band"))

    def test_no_match_is_remembered(self):
        self.library.find("Unknown Band")
        calls = len(self.client_mb.calls)
        self.assertIsNone(self.library.find("Unknown Band"))
        self.assertEqual(len(self.client_mb.calls), calls)

    def test_old_data_is_refreshed(self):
        from datetime import timedelta

        from django.utils import timezone

        from hub.models import Artist

        self.library.find("Pearl Jam")
        Artist.objects.update(fetched_at=timezone.now() - timedelta(days=31))
        self.library.find("Pearl Jam")
        self.assertEqual([c[0] for c in self.client_mb.calls].count("artist"), 2)


class ArtistProfileTests(TestCase):
    def profile(self):
        from django.utils import timezone

        from hub.models import Artist
        from hub.musicbrainz import artist_profile

        artist = Artist.objects.create(mbid=PEARL_JAM_ID, name="Pearl Jam", data=PEARL_JAM,
                                       release_groups=RELEASE_GROUPS, fetched_at=timezone.now())
        return artist_profile(artist)

    def test_facts(self):
        p = self.profile()
        self.assertEqual((p["type"], p["origin"], p["active"]), ("Group", "Seattle, United States", "1990–present"))
        self.assertEqual(p["genres"], ["grunge", "rock"])  # most votes first
        self.assertEqual(p["tags"], ["seattle"])  # genres are not repeated as tags
        self.assertEqual(p["image"], "https://commons.wikimedia.org/wiki/Special:FilePath/PJ.jpg?width=640")

    def test_members_current_first_with_roles(self):
        members = self.profile()["members"]
        self.assertEqual([m["name"] for m in members], ["Eddie Vedder", "Dave Krusen"])
        self.assertEqual(members[0]["roles"], ["lead vocals"])
        self.assertTrue(members[0]["original"])
        self.assertEqual(members[1]["years"], "1990–1991")

    def test_a_member_listed_once_per_role_appears_once(self):
        from django.utils import timezone

        from hub.models import Artist
        from hub.musicbrainz import artist_profile

        data = {**PEARL_JAM, "relations": PEARL_JAM["relations"] + [
            {"target-type": "artist", "type": "member of band", "direction": "backward", "begin": "1990", "ended": False,
             "attributes": ["guitar"], "artist": {"id": VEDDER_ID, "name": "Eddie Vedder"}},
        ]}
        artist = Artist.objects.create(mbid=PEARL_JAM_ID, name="Pearl Jam", data=data, release_groups=[], fetched_at=timezone.now())
        members = artist_profile(artist)["members"]
        self.assertEqual([m["name"] for m in members], ["Eddie Vedder", "Dave Krusen"])
        self.assertEqual(members[0]["roles"], ["lead vocals", "guitar"])

    def test_discography_sections(self):
        sections = {s["label"]: [r["title"] for r in s["releases"]] for s in self.profile()["discography"]}
        self.assertEqual(sections, {"Albums": ["Ten", "Vs."], "Singles": ["Alive"], "Live": ["Live on Two Legs"]})

    def test_links_are_grouped_and_named(self):
        links = {g["label"]: [i["label"] for i in g["items"]] for g in self.profile()["links"]}
        self.assertEqual(links, {"Listen": ["Spotify"], "Official": ["pearljam.com"]})


class ArtistPageTests(TestCase):
    def setUp(self):
        from hub.musicbrainz import MusicBrainzClient

        fake = FakeMusicBrainz()
        patcher = mock.patch("hub.musicbrainz.MusicBrainzClient", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = fake
        self.real_client = MusicBrainzClient

    def test_lookup_redirects_to_the_artist_page(self):
        response = self.client.get(reverse("hub:artist_lookup"), {"name": "Pearl Jam"})
        self.assertRedirects(response, reverse("hub:artist", args=[PEARL_JAM_ID]))

    def test_artist_page_shows_the_details(self):
        self.client.get(reverse("hub:artist_lookup"), {"name": "Pearl Jam"})
        response = self.client.get(reverse("hub:artist", args=[PEARL_JAM_ID]))
        for text in ["Pearl Jam", "Seattle, United States", "grunge", "Eddie Vedder", "lead vocals", "Ten", "Official site",
                     "Mookie Blaylock", "0000000123426109", "coverartarchive.org/release-group/aaaaaaaa-0000-0000-0000-000000000002"]:
            self.assertContains(response, text)

    def test_member_pages_are_fetched_when_first_opened(self):
        response = self.client.get(reverse("hub:artist", args=[VEDDER_ID]))
        self.assertContains(response, "Eddie Vedder")
        self.assertIn(("artist", VEDDER_ID), self.fake.calls)

    def test_pages_include_the_loading_overlay(self):
        with mock.patch.object(RadioModule, "stations", [FakeStation("WEBN", fail=True)]):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, 'id="loading-overlay"')
        self.assertContains(response, "Loading artist details")

    def test_unknown_name_shows_not_found(self):
        response = self.client.get(reverse("hub:artist_lookup"), {"name": "Unknown Band"})
        self.assertContains(response, "No artist found", status_code=404)

    def test_musicbrainz_down_shows_a_message(self):
        self.fake.search_artists = mock.Mock(side_effect=requests.ConnectionError("down"))
        response = self.client.get(reverse("hub:artist_lookup"), {"name": "Somebody New"})
        self.assertContains(response, "MusicBrainz did not respond", status_code=503)

    def test_radio_card_links_artists_to_their_page(self):
        stations = [FakeStation("WEBN", [song("Alive", "Pearl Jam", 9999999999)])]
        with mock.patch.object(RadioModule, "stations", stations):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, f'{reverse("hub:artist_lookup")}?name=Pearl%20Jam')
        self.assertContains(response, 'class="card-link"')


class MusicBrainzClientTests(TestCase):
    def test_identifies_itself_and_retries_once_when_told_to_slow_down(self):
        from hub.musicbrainz import USER_AGENT, MusicBrainzClient

        busy = mock.Mock(status_code=503)
        ok = mock.Mock(status_code=200, json=lambda: {"artists": []})
        client = MusicBrainzClient()
        client.min_interval = client.retry_delay = 0
        with mock.patch("hub.musicbrainz.requests.get", side_effect=[busy, ok]) as get:
            self.assertEqual(client.search_artists("Pearl Jam"), [])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], USER_AGENT)

    def test_waits_between_requests(self):
        from hub.musicbrainz import MusicBrainzClient

        ok = mock.Mock(status_code=200, json=lambda: {"artists": []})
        client = MusicBrainzClient()
        with mock.patch("hub.musicbrainz.requests.get", return_value=ok), \
                mock.patch("hub.musicbrainz.time.sleep") as sleep:
            client.search_artists("A")
            client.search_artists("B")
        self.assertTrue(any(call.args[0] > 0.5 for call in sleep.call_args_list))
