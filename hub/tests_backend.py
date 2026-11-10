"""Login, the admin, song previews, Wikipedia text, and artwork."""

from datetime import timedelta
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import spotify
from .models import Artist, ArtistName, Note, Play, Profile, Project, Song, SpotifyAccount, Task
from .modules.about import AboutModule
from .modules.brat import BratModule
from .modules.concerts import ConcertsModule, TicketmasterClient
from .modules.radio import RadioModule
from .music import MusicClient, SongLibrary, album_key, best_match, same_artist
from .musicbrainz import ArtistLibrary, MusicBrainzClient, artist_profile
from .names import song_key
from .wikipedia import WikipediaClient

MBID = "75af9d25-cf32-49c0-9192-60bd8e9784e6"


def saved_artist(**fields):
    defaults = {"mbid": MBID, "name": "Matchbox Twenty", "data": {"name": "Matchbox Twenty"}, "fetched_at": timezone.now(),
                "extras_checked_at": timezone.now()}
    return Artist.objects.create(**{**defaults, **fields})


class FakeWikipedia:
    def __init__(self):
        self.calls = 0

    def find(self, record):
        self.calls += 1
        return {"title": "Matchbox Twenty", "url": "https://en.wikipedia.org/wiki/Matchbox_Twenty",
                "summary": "An American rock band.", "description": "American rock band"}


class FakeMusic:
    def apple_albums(self, artist):
        return {"mad season": {"artwork": "https://apple.test/250x250bb.jpg", "url": "https://music.apple.com/album/1"}}


class FakeMusicBrainz:
    def __init__(self):
        self.calls = []

    def search_artists(self, name, limit=5):
        self.calls.append(name)
        return [{"id": MBID, "name": "Matchbox Twenty", "score": 100, "aliases": [{"name": "Matchbox 20"}]}]

    def artist(self, mbid):
        self.calls.append(mbid)
        return {"id": mbid, "name": "Matchbox Twenty", "relations": []}

    def release_groups(self, mbid, pages=15):
        return []


class MusicBrainzSearchTests(TestCase):
    def test_searches_aliases_as_well_as_names(self):
        client = MusicBrainzClient()
        client.min_interval = 0
        ok = mock.Mock(status_code=200, json=lambda: {"artists": []})
        with mock.patch("hub.musicbrainz.requests.get", return_value=ok) as get:
            client.search_artists("Matchbox 20")
        self.assertEqual(get.call_args.kwargs["params"]["query"], 'artist:"Matchbox 20" OR alias:"Matchbox 20"')

    def test_quotes_in_a_name_cannot_break_the_search(self):
        client = MusicBrainzClient()
        client.min_interval = 0
        ok = mock.Mock(status_code=200, json=lambda: {"artists": []})
        with mock.patch("hub.musicbrainz.requests.get", return_value=ok) as get:
            client.search_artists('The "Weird" Band')
        self.assertIn(r'artist:"The \"Weird\" Band"', get.call_args.kwargs["params"]["query"])

    def test_an_alias_match_finds_the_artist(self):
        library = ArtistLibrary(FakeMusicBrainz(), FakeWikipedia(), FakeMusic())
        self.assertEqual(library.find("Matchbox 20").name, "Matchbox Twenty")


class LibraryExtrasTests(TestCase):
    def setUp(self):
        self.fake = FakeMusicBrainz()
        self.wikipedia = FakeWikipedia()
        self.library = ArtistLibrary(self.fake, self.wikipedia, FakeMusic())

    def test_saves_wikipedia_text_and_apple_artwork(self):
        artist = self.library.save(MBID)
        self.assertEqual(artist.wikipedia_summary, "An American rock band.")
        self.assertIn("mad season", artist.apple_albums)
        self.assertIsNotNone(artist.extras_checked_at)

    def test_a_wikipedia_failure_still_saves_the_artist(self):
        self.wikipedia.find = mock.Mock(side_effect=requests.ConnectionError("down"))
        artist = self.library.save(MBID)
        self.assertEqual(artist.name, "Matchbox Twenty")
        self.assertIsNone(artist.extras_checked_at)

    def test_saved_artists_get_their_extras_once(self):
        saved_artist(extras_checked_at=None)
        self.library.save(MBID)
        self.library.save(MBID)
        self.assertEqual(self.wikipedia.calls, 1)

    def test_kept_edits_survive_the_refresh(self):
        saved_artist(name="My Name", locked=True, fetched_at=timezone.now() - timedelta(days=90))
        self.assertEqual(self.library.save(MBID).name, "My Name")
        self.assertEqual(self.fake.calls, [])

    def test_a_match_picked_by_hand_is_kept(self):
        other = "11111111-1111-1111-1111-111111111111"
        artist = saved_artist(mbid=other, name="Hand Picked")
        ArtistName.objects.create(name="Matchbox 20", artist=artist, checked_at=timezone.now() - timedelta(days=90))
        self.assertEqual(self.library.find("Matchbox 20"), artist)
        self.assertEqual(self.fake.calls, [])


def wikipedia_reply(**page):
    return mock.Mock(json=lambda: {"query": {"pages": [page]}})


class WikipediaClientTests(TestCase):
    page = {"title": "Pearl Jam", "fullurl": "https://en.wikipedia.org/wiki/Pearl_Jam", "extract": "A rock band.",
            "description": "American rock band"}

    def test_follows_the_wikidata_link(self):
        record = {"name": "Pearl Jam", "relations": [{"url": {"resource": "https://www.wikidata.org/wiki/Q142701"}}]}
        wikidata = mock.Mock(json=lambda: {"entities": {"Q142701": {"sitelinks": {"enwiki": {"title": "Pearl Jam"}}}}})
        with mock.patch("hub.wikipedia.requests.get", side_effect=[wikidata, wikipedia_reply(**self.page)]) as get:
            page = WikipediaClient().find(record)
        self.assertEqual(page["summary"], "A rock band.")
        self.assertEqual(get.call_args.kwargs["params"]["titles"], "Pearl Jam")

    def test_uses_a_direct_wikipedia_link(self):
        record = {"name": "X", "relations": [{"url": {"resource": "https://en.wikipedia.org/wiki/Guns_N%27_Roses"}}]}
        self.assertEqual(WikipediaClient().linked_title(record), "Guns N' Roses")

    def test_a_page_found_by_name_must_be_about_music(self):
        fruit = wikipedia_reply(title="Apple", fullurl="u", extract="A fruit.", description="Edible fruit")
        with mock.patch("hub.wikipedia.requests.get", return_value=fruit):
            self.assertIsNone(WikipediaClient().find({"name": "Apple", "relations": []}))

    def test_a_page_found_by_name_can_be_a_band(self):
        with mock.patch("hub.wikipedia.requests.get", return_value=wikipedia_reply(**self.page)):
            self.assertEqual(WikipediaClient().find({"name": "Pearl Jam", "relations": []})["title"], "Pearl Jam")

    def test_disambiguation_pages_are_skipped(self):
        reply = wikipedia_reply(title="Bush", fullurl="u", extract="May refer to", pageprops={"disambiguation": ""})
        with mock.patch("hub.wikipedia.requests.get", return_value=reply):
            self.assertIsNone(WikipediaClient().page("Bush"))


def apple_song(**fields):
    return {"artistName": "Matchbox Twenty", "trackName": "3 am", "collectionName": "Yourself or Someone Like You",
            "previewUrl": "https://apple.test/preview.m4a", "trackViewUrl": "https://music.apple.com/song/1",
            "artworkUrl100": "https://apple.test/100x100bb.jpg", **fields}


class FakeMusicClient:
    def __init__(self, apple=None, deezer=None):
        self.apple, self.deezer = apple, deezer
        self.calls = []

    def apple_song(self, artist, title):
        self.calls.append("apple")
        return self.apple

    def deezer_song(self, artist, title):
        self.calls.append("deezer")
        return self.deezer


class SongLibraryTests(TestCase):
    def test_uses_apple_first_and_skips_deezer(self):
        client = FakeMusicClient(apple=apple_song())
        song = SongLibrary(client).find("Matchbox 20", "3AM")
        self.assertEqual(song.apple_preview_url, "https://apple.test/preview.m4a")
        self.assertEqual(song.artwork_url, "https://apple.test/250x250bb.jpg")
        self.assertEqual(client.calls, ["apple"])

    def test_falls_back_to_deezer(self):
        deezer = {"id": 42, "link": "https://deezer.test/track/42", "album": {"title": "Album", "cover_medium": "c.jpg"}}
        song = SongLibrary(FakeMusicClient(deezer=deezer)).find("Metallica", "Enter Sandman")
        self.assertEqual(song.deezer_track_id, 42)
        self.assertEqual(song.album, "Album")
        self.assertTrue(song.has_preview)

    def test_remembers_a_song_with_no_preview(self):
        client = FakeMusicClient()
        library = SongLibrary(client)
        self.assertFalse(library.find("Local Band", "Demo").has_preview)
        library.find("Local Band", "Demo")
        self.assertEqual(client.calls, ["apple", "deezer"])

    def test_is_saved_once_however_it_is_spelled(self):
        library = SongLibrary(FakeMusicClient(apple=apple_song()))
        self.assertEqual(library.find("Matchbox 20", "3AM").pk, library.find("MATCHBOX 20", "3 AM").pk)

    def test_links_to_the_saved_artist(self):
        artist = saved_artist()
        ArtistName.objects.create(name="Matchbox 20", artist=artist, checked_at=timezone.now())
        self.assertEqual(SongLibrary(FakeMusicClient()).find("Matchbox 20", "3AM").artist, artist)

    def test_kept_edits_survive_the_refresh(self):
        old = timezone.now() - timedelta(days=90)
        Song.objects.create(artist_name="A", title="B", album="Mine", locked=True, checked_at=old)
        client = FakeMusicClient(apple=apple_song())
        self.assertEqual(SongLibrary(client).find("A", "B").album, "Mine")
        self.assertEqual(client.calls, [])

    def test_old_songs_are_refreshed(self):
        old = timezone.now() - timedelta(days=31)
        Song.objects.create(artist_name="A", title="B", apple_preview_url="https://old", checked_at=old)
        song = SongLibrary(FakeMusicClient(apple=apple_song())).find("A", "B")
        self.assertEqual(song.apple_preview_url, "https://apple.test/preview.m4a")


class MatchingTests(TestCase):
    read = staticmethod(lambda item: item)

    def test_same_artist(self):
        self.assertTrue(same_artist("Tame Impala [+] Jennie", "Tame Impala"))
        self.assertTrue(same_artist("Guns N Roses", "Guns N' Roses"))
        self.assertFalse(same_artist("Pearl Jam", "Metallica"))
        self.assertFalse(same_artist("Pearl Jam", ""))

    def test_prefers_an_exact_title(self):
        items = [("U2", "One (Remastered)"), ("U2", "One")]
        self.assertEqual(best_match(items, "U2", "One", self.read), ("U2", "One"))

    def test_accepts_extra_words(self):
        items = [("AC/DC", "Highway to Hell (Live)")]
        self.assertEqual(best_match(items, "AC/DC", "Highway to Hell", self.read), items[0])

    def test_rejects_another_artists_song(self):
        self.assertIsNone(best_match([("Tribute Act", "One")], "U2", "One", self.read))

    def test_album_key(self):
        self.assertEqual(album_key("Ten (Remastered)"), "ten")
        self.assertEqual(album_key("Alive - Single"), "alive")
        self.assertEqual(album_key("Mad Season"), "mad season")


class AppleAlbumsTests(TestCase):
    def test_keeps_only_this_artist_and_uses_larger_artwork(self):
        results = [
            {"artistName": "Pearl Jam", "collectionName": "Ten", "artworkUrl100": "https://a/100x100bb.jpg",
             "collectionViewUrl": "https://music.apple.com/ten"},
            {"artistName": "Pearl Jam Tribute", "collectionName": "Ten Covers", "artworkUrl100": "https://b/100x100bb.jpg"},
        ]
        reply = mock.Mock(json=lambda: {"results": results})
        with mock.patch("hub.music.requests.get", return_value=reply):
            albums = MusicClient().apple_albums("Pearl Jam")
        self.assertEqual(list(albums), ["ten"])
        self.assertEqual(albums["ten"]["artwork"], "https://a/250x250bb.jpg")


class SongPreviewTests(TestCase):
    def test_goes_to_the_apple_preview(self):
        song = Song.objects.create(artist_name="A", title="B", apple_preview_url="https://apple.test/p.m4a")
        response = self.client.get(reverse("hub:song_preview", args=[song.pk]))
        self.assertRedirects(response, "https://apple.test/p.m4a", fetch_redirect_response=False)

    def test_fetches_a_fresh_deezer_address(self):
        song = Song.objects.create(artist_name="A", title="B", deezer_track_id=42)
        with mock.patch.object(MusicClient, "deezer_preview", return_value="https://deezer.test/fresh.mp3") as preview:
            response = self.client.get(reverse("hub:song_preview", args=[song.pk]))
        preview.assert_called_once_with(42)
        self.assertRedirects(response, "https://deezer.test/fresh.mp3", fetch_redirect_response=False)

    def test_no_preview_is_not_found(self):
        song = Song.objects.create(artist_name="A", title="B")
        self.assertEqual(self.client.get(reverse("hub:song_preview", args=[song.pk])).status_code, 404)

    def test_deezer_being_down_is_reported(self):
        song = Song.objects.create(artist_name="A", title="B", deezer_track_id=42)
        with mock.patch.object(MusicClient, "deezer_preview", side_effect=requests.ConnectionError("down")):
            self.assertEqual(self.client.get(reverse("hub:song_preview", args=[song.pk])).status_code, 503)


class RadioPageSongTests(TestCase):
    def station(self):
        return mock.Mock(**{"recent.return_value": [{
            "title": "3AM", "artist": "Matchbox 20", "image": "", "playing": True, "played_at": timezone.now(), "end": 0,
        }]})

    def test_shows_a_player_once_a_song_is_saved(self):
        song = Song.objects.create(artist_name="Matchbox 20", title="3AM", apple_preview_url="https://a/p.m4a",
                                   apple_url="https://music.apple.com/song/1")
        with mock.patch.object(RadioModule, "stations", [self.station()]):
            response = self.client.get(reverse("hub:radio"))
        self.assertContains(response, reverse("hub:song_preview", args=[song.pk]))
        self.assertContains(response, "https://music.apple.com/song/1")
        self.assertContains(response, "music.youtube.com/search?q=Matchbox%2020%203AM")

    def test_works_before_a_song_is_saved(self):
        with mock.patch.object(RadioModule, "stations", [self.station()]):
            response = self.client.get(reverse("hub:radio"))
        self.assertContains(response, "3AM")
        self.assertNotContains(response, "play-button")


class ArtistPageExtrasTests(TestCase):
    def test_shows_wikipedia_with_credit_and_songs(self):
        artist = saved_artist(wikipedia_title="Matchbox Twenty", wikipedia_url="https://en.wikipedia.org/wiki/Matchbox_Twenty",
                              wikipedia_summary="An American rock band.")
        Song.objects.create(artist_name="Matchbox 20", title="3AM", artist=artist, apple_preview_url="https://a/p.m4a")
        response = self.client.get(reverse("hub:artist", args=[MBID]))
        self.assertContains(response, "An American rock band.")
        self.assertNotContains(response, "Read more")
        self.assertContains(response, "CC BY-SA 4.0")
        self.assertContains(response, "Heard on the radio")
        self.assertContains(response, 'class="play-button"', count=1)

    def test_apple_artwork_fills_in_for_a_missing_cover(self):
        group = {"id": "aaaaaaaa-0000-0000-0000-000000000001", "title": "Mad Season (Deluxe)", "primary-type": "Album"}
        artist = saved_artist(release_groups=[group], apple_albums=FakeMusic().apple_albums("x"))
        release = artist_profile(artist)["discography"][0]["releases"][0]
        self.assertEqual(release["apple_artwork"], "https://apple.test/250x250bb.jpg")
        self.assertEqual(release["apple_url"], "https://music.apple.com/album/1")
        response = self.client.get(reverse("hub:artist", args=[MBID]))
        self.assertContains(response, 'data-fallback="https://apple.test/250x250bb.jpg"')


class LoginTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("editor", password="secret", is_staff=True)

    def test_visitors_cannot_change_tasks(self):
        response = self.client.post(reverse("hub:todo"), {"action": "add", "title": "Hack"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])
        self.assertFalse(Task.objects.exists())

    def test_editors_see_the_admin_link(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("hub:todo"))
        self.assertContains(response, reverse("admin:index"))
        self.assertContains(response, "Log out")


class AdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("boss", password="secret"))

    def test_every_list_and_add_page_opens(self):
        for model in ("task", "note", "artist", "artistname", "song"):
            self.assertEqual(self.client.get(reverse(f"admin:hub_{model}_changelist")).status_code, 200)
            self.assertEqual(self.client.get(reverse(f"admin:hub_{model}_add")).status_code, 200)

    def test_every_edit_page_opens(self):
        artist = saved_artist()
        objects = {
            "task": Task.objects.create(title="T"), "note": Note.objects.create(title="N"), "artist": artist,
            "artistname": ArtistName.objects.create(name="X", checked_at=timezone.now()),
            "song": Song.objects.create(artist_name="A", title="B"),
        }
        for model, item in objects.items():
            self.assertEqual(self.client.get(reverse(f"admin:hub_{model}_change", args=[item.pk])).status_code, 200)

    def test_adds_an_artist_from_a_musicbrainz_id(self):
        with mock.patch("hub.musicbrainz.MusicBrainzClient", return_value=FakeMusicBrainz()), \
                mock.patch("hub.musicbrainz.WikipediaClient", return_value=FakeWikipedia()), \
                mock.patch("hub.musicbrainz.MusicClient", return_value=FakeMusic()):
            response = self.client.post(reverse("admin:hub_artist_add"), {"mbid": MBID})
        self.assertEqual(response.status_code, 302)
        artist = Artist.objects.get(mbid=MBID)
        self.assertEqual(artist.name, "Matchbox Twenty")
        self.assertEqual(artist.wikipedia_summary, "An American rock band.")

    def test_a_bad_musicbrainz_id_shows_an_error(self):
        client = mock.Mock(**{"artist.side_effect": requests.HTTPError("404")})
        with mock.patch("hub.musicbrainz.MusicBrainzClient", return_value=client), \
                mock.patch("hub.musicbrainz.WikipediaClient"), mock.patch("hub.musicbrainz.MusicClient"):
            response = self.client.post(reverse("admin:hub_artist_add"), {"mbid": MBID})
        self.assertContains(response, "MusicBrainz has no artist with that ID")
        self.assertFalse(Artist.objects.exists())

    def test_edits_an_artist_with_no_releases(self):
        artist = saved_artist()
        response = self.client.post(reverse("admin:hub_artist_change", args=[artist.pk]), {
            "name": "Edited", "locked": "on", "wikipedia_title": "", "wikipedia_url": "", "wikipedia_summary": "",
            "data": '{"name": "Matchbox Twenty"}', "release_groups": "[]", "apple_albums": "{}",
        })
        self.assertEqual(response.status_code, 302)
        artist.refresh_from_db()
        self.assertEqual(artist.name, "Edited")
        self.assertTrue(artist.locked)

    def test_deletes_an_artist(self):
        artist = saved_artist()
        response = self.client.post(reverse("admin:hub_artist_delete", args=[artist.pk]), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Artist.objects.exists())

    def test_links_a_radio_name_to_an_artist(self):
        artist = saved_artist()
        entry = ArtistName.objects.create(name="Matchbox 20", checked_at=timezone.now())
        self.client.post(reverse("admin:hub_artistname_change", args=[entry.pk]), {
            "name": "Matchbox 20", "artist": artist.pk, "checked_at_0": "2026-11-05", "checked_at_1": "12:00:00",
        })
        entry.refresh_from_db()
        self.assertEqual(entry.artist, artist)

    def test_adding_a_song_looks_up_its_preview(self):
        with mock.patch.object(MusicClient, "apple_song", return_value=apple_song()):
            self.client.post(reverse("admin:hub_song_add"), {"title": "3AM", "artist_name": "Matchbox 20"})
        self.assertEqual(Song.objects.get().apple_preview_url, "https://apple.test/preview.m4a")


class ListenerSongTests(TestCase):
    def setUp(self):
        from .management.commands.listen_radio import Command

        self.command = Command(stdout=mock.Mock(), stderr=mock.Mock())

    def test_looks_up_a_few_songs_each_check(self):
        library = mock.Mock()
        waiting = dict.fromkeys([("A", "1"), ("B", "2"), ("C", "3"), ("D", "4")])
        self.command.look_up_songs(library, waiting)
        self.assertEqual(library.find.call_args_list, [mock.call("A", "1"), mock.call("B", "2"), mock.call("C", "3")])
        self.assertEqual(list(waiting), [("D", "4")])

    def test_one_failed_song_does_not_stop_the_rest(self):
        library = mock.Mock(**{"find.side_effect": [ValueError("bad"), mock.DEFAULT]})
        self.command.look_up_songs(library, dict.fromkeys([("A", "1"), ("B", "2")]))
        self.assertEqual(library.find.call_count, 2)


class HomeCardTests(TestCase):
    def home(self):
        with mock.patch.object(RadioModule, "stations", []):
            return self.client.get(reverse("hub:home"))

    def test_shows_real_tasks_and_the_latest_note(self):
        Task.objects.create(title="Buy milk")
        Task.objects.create(title="Finished", done=True)
        Note.objects.create(title="Idea", body="Some text")
        response = self.home()
        self.assertContains(response, "Buy milk")
        self.assertNotContains(response, "Finished")
        self.assertContains(response, "Idea")

    def test_outside_services_load_after_the_page(self):
        response = self.home()
        for slug in ("weather", "news", "concerts"):
            self.assertContains(response, f'data-card-url="{reverse("hub:" + slug)}?card=1"')

    def test_a_module_can_return_just_its_card(self):
        with mock.patch("hub.modules.news.NewsModule.client_class") as client:
            client.return_value.top_stories.return_value = [
                {"title": "Big story - BBC", "link": "https://example.com", "source": "BBC", "published": ""},
            ]
            response = self.client.get(reverse("hub:news"), {"card": 1})
        self.assertContains(response, "Big story")
        self.assertNotContains(response, "<html")

    def test_pages_without_a_card_ignore_the_request_for_one(self):
        self.assertContains(self.client.get(reverse("hub:todo"), {"card": 1}), "<html")

    def test_radio_card_uses_saved_artwork(self):
        Song.objects.create(artist_name="Matchbox 20", title="3AM", artwork_url="https://apple.test/art.jpg")
        station = mock.Mock(**{"recent.return_value": [{
            "title": "3AM", "artist": "Matchbox 20", "image": "", "playing": True, "played_at": timezone.now(), "end": 0,
        }]})
        with mock.patch.object(RadioModule, "stations", [station]):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, "https://apple.test/art.jpg")


class WikipediaDisplayTests(TestCase):
    def test_long_text_goes_behind_read_more(self):
        saved_artist(wikipedia_title="T", wikipedia_url="https://w", wikipedia_summary="First paragraph.\nSecond paragraph.")
        response = self.client.get(reverse("hub:artist", args=[MBID]))
        self.assertContains(response, "<p>First paragraph.</p>")
        self.assertContains(response, "Read more")

    def test_uses_the_wikipedia_photo_when_musicbrainz_has_none(self):
        artist = saved_artist(wikipedia_image="https://upload.wikimedia.org/band.jpg")
        self.assertEqual(artist_profile(artist)["image"], "https://upload.wikimedia.org/band.jpg")


class LiveListeningTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(artist_name="Matchbox 20", title="3AM", apple_preview_url="https://a/p.m4a")

    def station(self):
        return mock.Mock(
            stream_url="https://stream.test/live", **{"recent.return_value": [{
                "title": "3AM", "artist": "Matchbox 20", "image": "", "playing": True, "played_at": timezone.now(), "end": 0,
            }]},
        )

    def test_each_station_has_a_live_stream(self):
        from .modules.radio import IHeartStation, TritonStation

        self.assertEqual(IHeartStation("A", "1", 1701).stream_url, "https://stream.revma.ihrhls.com/zc1701")
        self.assertIn("WKRQFM.mp3", TritonStation("B", "2", "WKRQFM").stream_url)

    def test_home_card_offers_live_and_the_preview(self):
        with mock.patch.object(RadioModule, "stations", [self.station()]):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, 'data-src="https://stream.test/live"')
        self.assertContains(response, "Listen live")
        self.assertContains(response, reverse("hub:song_preview", args=[self.song.pk]))

    def test_radio_page_offers_live(self):
        with mock.patch.object(RadioModule, "stations", [self.station()]):
            response = self.client.get(reverse("hub:radio"))
        self.assertContains(response, 'data-src="https://stream.test/live"')

    def test_stations_without_a_stream_show_no_button(self):
        station = self.station()
        station.stream_url = ""
        with mock.patch.object(RadioModule, "stations", [station]):
            self.assertNotContains(self.client.get(reverse("hub:home")), "live-button")

    def test_songs_link_to_spotify(self):
        self.assertEqual(self.song.spotify_url, "https://open.spotify.com/search/Matchbox%2020%203AM")

    def test_the_card_updates_when_a_preview_is_found(self):
        from .listener import RadioListener

        station = mock.Mock()
        station.name = "WEBN"
        track = {"title": "3AM", "artist": "A", "playing": True}
        before = RadioListener.signature({"stations": [{"station": station, "tracks": [track]}]})
        after = RadioListener.signature({"stations": [{"station": station, "tracks": [{**track, "song": self.song}]}]})
        self.assertNotEqual(before, after)


SPOTIFY_TRACK = {
    "name": "3AM", "artists": [{"name": "Matchbox Twenty"}, {"name": "Guest"}],
    "album": {"name": "Yourself or Someone Like You", "images": [{"url": "https://i.scdn.co/big.jpg"}]},
    "external_urls": {"spotify": "https://open.spotify.com/track/1"},
}


class FakeSpotify:
    def __init__(self, playing=None, last=None):
        self.playing, self.last = playing, last
        self.refreshed = 0

    def refresh(self, refresh_token):
        self.refreshed += 1
        return {"access_token": "new", "expires_in": 3600}

    def currently_playing(self, token):
        return self.playing

    def last_played(self, token):
        return self.last


@override_settings(SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REDIRECT_URI="http://127.0.0.1:8001/spotify/callback/")
class SpotifyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def account(self, **fields):
        defaults = {"access_token": "token", "refresh_token": "refresh", "expires_at": timezone.now() + timedelta(hours=1)}
        return SpotifyAccount.objects.create(**{**defaults, **fields})

    def state(self):
        from .views import SPOTIFY_STATE_SALT

        return signing.dumps("connect", salt=SPOTIFY_STATE_SALT)

    def test_not_connected_shows_nothing(self):
        self.assertIsNone(spotify.listening(FakeSpotify()))

    def test_prefers_what_is_playing_now(self):
        self.account()
        client = FakeSpotify(playing={"title": "Now"}, last={"title": "Before"})
        self.assertEqual(spotify.listening(client)["title"], "Now")

    def test_falls_back_to_the_last_song(self):
        self.account()
        self.assertEqual(spotify.listening(FakeSpotify(last={"title": "Before"}))["title"], "Before")

    def test_renews_an_expired_login_and_keeps_the_refresh_token(self):
        account = self.account(expires_at=timezone.now() - timedelta(minutes=1))
        client = FakeSpotify(last={"title": "Before"})
        spotify.listening(client)
        account.refresh_from_db()
        self.assertEqual(client.refreshed, 1)
        self.assertEqual(account.access_token, "new")
        self.assertEqual(account.refresh_token, "refresh")

    def test_results_are_kept_briefly(self):
        self.account()
        spotify.listening(FakeSpotify(last={"title": "First"}))
        self.assertEqual(spotify.listening(FakeSpotify(last={"title": "Second"}))["title"], "First")

    def test_reads_the_playing_track(self):
        reply = mock.Mock(status_code=200, json=lambda: {"is_playing": True, "item": SPOTIFY_TRACK})
        with mock.patch("hub.spotify.requests.get", return_value=reply) as get:
            track = spotify.SpotifyClient().currently_playing("token")
        self.assertEqual(track["artist"], "Matchbox Twenty, Guest")
        self.assertEqual(track["first_artist"], "Matchbox Twenty")
        self.assertEqual(track["artwork"], "https://i.scdn.co/big.jpg")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer token")

    def test_nothing_playing_returns_none(self):
        with mock.patch("hub.spotify.requests.get", return_value=mock.Mock(status_code=204)):
            self.assertIsNone(spotify.SpotifyClient().currently_playing("token"))

    def test_paused_music_does_not_count_as_playing(self):
        reply = mock.Mock(status_code=200, json=lambda: {"is_playing": False, "item": SPOTIFY_TRACK})
        with mock.patch("hub.spotify.requests.get", return_value=reply):
            self.assertIsNone(spotify.SpotifyClient().currently_playing("token"))

    def test_reads_the_last_song(self):
        data = {"items": [{"track": SPOTIFY_TRACK, "played_at": "2026-11-05T12:00:00.000Z"}]}
        with mock.patch("hub.spotify.requests.get", return_value=mock.Mock(status_code=200, json=lambda: data)):
            track = spotify.SpotifyClient().last_played("token")
        self.assertFalse(track["playing"])
        self.assertEqual(track["played_at"].year, 2026)

    def test_card_shows_the_song(self):
        track = {"title": "3AM", "artist": "Matchbox Twenty", "first_artist": "Matchbox Twenty", "album": "A", "artwork": "",
                 "url": "https://open.spotify.com/track/1", "playing": True, "played_at": None}
        with mock.patch("hub.spotify.listening", return_value=track):
            response = self.client.get(reverse("hub:spotify_card"))
        self.assertContains(response, "Playing now")
        self.assertContains(response, "Open in Spotify")
        self.assertContains(response, "name=Matchbox%20Twenty")

    def test_card_reports_spotify_being_down(self):
        with mock.patch("hub.spotify.listening", side_effect=requests.ConnectionError("down")):
            self.assertContains(self.client.get(reverse("hub:spotify_card")), "did not respond")

    def test_only_the_owner_sees_connect(self):
        self.assertNotContains(self.client.get(reverse("hub:spotify_card")), "Connect Spotify")
        self.client.force_login(User.objects.create_user("editor", password="secret", is_staff=True))
        self.assertContains(self.client.get(reverse("hub:spotify_card")), "Connect Spotify")

    def test_visitors_cannot_start_a_connection(self):
        response = self.client.get(reverse("hub:spotify_connect"))
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_the_owner_is_sent_to_spotify(self):
        self.client.force_login(User.objects.create_user("editor", password="secret", is_staff=True))
        response = self.client.get(reverse("hub:spotify_connect"))
        self.assertIn("accounts.spotify.com/authorize", response["Location"])
        self.assertIn("user-read-recently-played", response["Location"])
        self.assertIn("127.0.0.1%3A8001", response["Location"])

    def test_callback_saves_the_login(self):
        tokens = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
        with mock.patch.object(spotify.SpotifyClient, "exchange_code", return_value=tokens):
            response = self.client.get(reverse("hub:spotify_callback"), {"code": "c", "state": self.state()})
        self.assertRedirects(response, reverse("hub:home"), fetch_redirect_response=False)
        self.assertEqual(SpotifyAccount.objects.get().refresh_token, "r")

    def test_callback_rejects_a_forged_request(self):
        with mock.patch.object(spotify.SpotifyClient, "exchange_code") as exchange:
            response = self.client.get(reverse("hub:spotify_callback"), {"code": "c", "state": "forged"})
        self.assertEqual(response.status_code, 400)
        exchange.assert_not_called()
        self.assertFalse(SpotifyAccount.objects.exists())

    def test_refusing_access_saves_nothing(self):
        response = self.client.get(reverse("hub:spotify_callback"), {"error": "access_denied", "state": self.state()})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SpotifyAccount.objects.exists())

    def test_the_admin_never_shows_the_tokens(self):
        account = self.account(access_token="secret-access", refresh_token="secret-refresh")
        self.client.force_login(User.objects.create_superuser("boss", password="secret"))
        response = self.client.get(reverse("admin:hub_spotifyaccount_change", args=[account.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "secret-access")
        self.assertNotContains(response, "secret-refresh")


class SpotifyHomeTests(TestCase):
    def home(self):
        with mock.patch.object(RadioModule, "stations", []):
            return self.client.get(reverse("hub:home"))

    @override_settings(SPOTIFY_PLAYLIST_URL="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc")
    def test_shows_the_playlist_player(self):
        response = self.home()
        self.assertContains(response, "open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M")
        self.assertContains(response, "encrypted-media")

    def test_one_playlist_needs_no_buttons(self):
        with override_settings(SPOTIFY_PLAYLIST_URL="https://open.spotify.com/playlist/aaa"):
            self.assertNotContains(self.home(), "data-playlist")

    @override_settings(SPOTIFY_PLAYLIST_URL="https://open.spotify.com/playlist/aaa?si=1,https://open.spotify.com/playlist/bbb?si=2")
    def test_several_playlists_get_buttons(self):
        response = self.home()
        self.assertContains(response, 'data-playlist="https://open.spotify.com/embed/playlist/aaa?theme=0"')
        self.assertContains(response, 'data-playlist="https://open.spotify.com/embed/playlist/bbb?theme=0"')
        self.assertContains(response, 'src="https://open.spotify.com/embed/playlist/aaa?theme=0"')

    @override_settings(SPOTIFY_PLAYLIST_URL="https://example.com/not-a-playlist")
    def test_ignores_a_link_that_is_not_a_playlist(self):
        self.assertNotContains(self.home(), "<iframe")

    def test_each_station_is_its_own_card(self):
        stations = [
            mock.Mock(recent=mock.Mock(return_value=[]), stream_url=""),
            mock.Mock(recent=mock.Mock(return_value=[]), stream_url=""),
        ]
        with mock.patch.object(RadioModule, "stations", stations):
            response = self.client.get(reverse("hub:home"))
        self.assertContains(response, 'class="card card-station"', count=2)
        self.assertNotContains(response, "card-radio")


def staff_user():
    return User.objects.create_user("owner", password="secret", is_staff=True)


TICKETMASTER_EVENT = {
    "name": "Pearl Jam", "url": "https://www.ticketmaster.com/e/1",
    "dates": {"start": {"localDate": "2026-12-01", "localTime": "19:30:00"}},
    "images": [{"url": "https://s1.ticketm.net/small.jpg", "width": 100}, {"url": "https://s1.ticketm.net/big.jpg", "width": 640}],
    "_embedded": {"venues": [{"name": "Heritage Bank Center"}], "attractions": [{"name": "Pearl Jam"}]},
}


class FakeTicketmaster:
    def events(self, city, state, size=30):
        return [{**TICKETMASTER_EVENT, "name": f"{city} show"}]


@override_settings(TICKETMASTER_API_KEY="key")
@mock.patch.object(ConcertsModule, "client_class", FakeTicketmaster)
class ConcertsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_lists_shows_from_all_three_cities(self):
        response = self.client.get(reverse("hub:concerts"))
        for city in ("Cincinnati", "Dayton", "Columbus"):
            self.assertContains(response, f"{city} show")
        self.assertContains(response, "Heritage Bank Center")
        self.assertContains(response, "https://s1.ticketm.net/big.jpg")

    def test_filters_by_city(self):
        response = self.client.get(reverse("hub:concerts"), {"city": "Dayton"})
        self.assertContains(response, "Dayton show")
        self.assertNotContains(response, "Columbus show")

    def test_home_card(self):
        self.assertContains(self.client.get(reverse("hub:concerts"), {"card": 1}), "Dec 1")

    def test_results_are_remembered(self):
        with mock.patch.object(FakeTicketmaster, "events", return_value=[TICKETMASTER_EVENT]) as events:
            self.client.get(reverse("hub:concerts"))
            self.client.get(reverse("hub:concerts"))
        self.assertEqual(events.call_count, 3)

    def test_service_down(self):
        with mock.patch.object(FakeTicketmaster, "events", side_effect=requests.ConnectionError("down")):
            self.assertContains(self.client.get(reverse("hub:concerts")), "did not respond")

    @override_settings(TICKETMASTER_API_KEY="")
    def test_no_key_explains_itself(self):
        self.assertContains(self.client.get(reverse("hub:concerts")), "Ticketmaster API key")

    def test_requests_music_for_the_right_city(self):
        reply = mock.Mock(json=lambda: {"_embedded": {"events": []}})
        with mock.patch("hub.modules.concerts.requests.get", return_value=reply) as get:
            TicketmasterClient().events("Dayton", "OH")
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["city"], params["stateCode"], params["classificationName"]), ("Dayton", "OH", "music"))


def calendar_file(today):
    day = today.strftime("%Y%m%d")
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:1
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:{day}
SUMMARY:Holiday
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTAMP:20260101T000000Z
DTSTART:{day}T150000Z
DTEND:{day}T160000Z
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Standup
LOCATION:Kitchen
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode()


@override_settings(CALENDAR_URLS=["webcal://p01-caldav.icloud.com/published/2/abc"])
class AgendaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.today = timezone.localdate()

    def reply(self):
        return mock.Mock(content=calendar_file(self.today))

    def test_visitors_cannot_see_it(self):
        response = self.client.get(reverse("hub:agenda"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_visitors_cannot_get_the_card_either(self):
        self.assertEqual(self.client.get(reverse("hub:agenda"), {"card": 1}).status_code, 302)

    def test_hidden_from_visitors_on_home_and_in_the_menu(self):
        with mock.patch.object(RadioModule, "stations", []):
            response = self.client.get(reverse("hub:home"))
        self.assertNotContains(response, reverse("hub:agenda"))

    def test_shows_all_day_and_repeating_events(self):
        self.client.force_login(staff_user())
        with mock.patch("hub.modules.agenda.requests.get", return_value=self.reply()) as get:
            response = self.client.get(reverse("hub:agenda"))
        self.assertTrue(get.call_args.args[0].startswith("https://"))
        self.assertContains(response, "Holiday")
        self.assertContains(response, "All day")
        self.assertContains(response, "Standup", count=3)
        self.assertContains(response, "Kitchen")

    def test_one_broken_calendar_is_reported(self):
        self.client.force_login(staff_user())
        with mock.patch("hub.modules.agenda.requests.get", side_effect=requests.ConnectionError("down")):
            self.assertContains(self.client.get(reverse("hub:agenda")), "could not be read")

    @override_settings(CALENDAR_URLS=[])
    def test_no_calendars_explains_itself(self):
        self.client.force_login(staff_user())
        self.assertContains(self.client.get(reverse("hub:agenda")), "Add your calendar links")


def play(station, artist, title, when):
    return Play.objects.create(station=station, artist_name=artist, title=title, song_key=song_key(artist, title), played_at=when)


class ChartsTests(TestCase):
    def setUp(self):
        self.now = timezone.localtime().replace(microsecond=0)

    def test_counts_plays_for_each_station(self):
        for minutes in (1, 2):
            play("WEBN", "Nirvana", "Lithium", self.now - timedelta(minutes=minutes))
        play("WEBN", "Metallica", "One", self.now - timedelta(minutes=3))
        play("WKRQ", "Ashe", "Moral", self.now - timedelta(minutes=4))
        stations = self.client.get(reverse("hub:charts")).context["stations"]
        self.assertEqual([station["name"] for station in stations], ["WEBN", "WKRQ"])
        top = stations[0]["songs"][0]
        self.assertEqual((top["title"], top["plays"], top["bar"]), ("Lithium", 2, 100))
        self.assertEqual(stations[0]["songs"][1]["bar"], 50)
        self.assertEqual(stations[0]["artists"][0]["artist"], "Nirvana")

    def test_different_spellings_count_as_one_song(self):
        play("WEBN", "Nirvana", "Lithium", self.now - timedelta(minutes=1))
        play("WEBN", "NIRVANA", "LITHIUM", self.now - timedelta(minutes=2))
        songs = self.client.get(reverse("hub:charts")).context["stations"][0]["songs"]
        self.assertEqual(len(songs), 1)
        self.assertEqual(songs[0]["plays"], 2)

    def test_weeks_are_kept_apart(self):
        old = self.now - timedelta(days=14)
        play("WEBN", "Nirvana", "Lithium", old)
        self.assertNotContains(self.client.get(reverse("hub:charts")), "Lithium")
        response = self.client.get(reverse("hub:charts"), {"week": old.date().isoformat()})
        self.assertContains(response, "Lithium")
        self.assertContains(response, "Later")

    def test_a_bad_week_falls_back_to_this_week(self):
        self.assertEqual(self.client.get(reverse("hub:charts"), {"week": "soon"}).status_code, 200)

    def test_empty_week_explains_itself(self):
        self.assertContains(self.client.get(reverse("hub:charts")), "No plays saved")

    def test_home_card_shows_the_top_songs(self):
        play("WEBN", "Nirvana", "Lithium", self.now - timedelta(minutes=1))
        with mock.patch.object(RadioModule, "stations", []):
            self.assertContains(self.client.get(reverse("hub:home")), "Lithium")

    def test_saved_songs_get_a_preview_button(self):
        Song.objects.create(artist_name="Nirvana", title="Lithium", apple_preview_url="https://a/p.m4a")
        play("WEBN", "Nirvana", "Lithium", self.now - timedelta(minutes=1))
        self.assertContains(self.client.get(reverse("hub:charts")), 'class="play-button"')

    def test_the_listener_saves_each_play_once(self):
        when = self.now - timedelta(minutes=5)
        station = mock.Mock(**{"recent.return_value": [{
            "title": "3AM", "artist": "Matchbox 20", "image": "", "playing": False, "played_at": when, "end": 0,
        }]})
        station.name = "WEBN"
        with mock.patch.object(RadioModule, "stations", [station]):
            self.assertEqual(RadioModule.remember_recent(), [("Matchbox 20", "3AM")])
            RadioModule.remember_recent()
        self.assertEqual(Play.objects.count(), 1)


class ListeningTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def connect(self):
        SpotifyAccount.objects.create(access_token="t", refresh_token="r", expires_at=timezone.now() + timedelta(hours=1))

    def test_not_connected_explains_itself(self):
        self.assertContains(self.client.get(reverse("hub:listening")), "Connect Spotify")

    def test_shows_top_tracks_and_artists(self):
        self.connect()

        def top(client, token, kind, time_range):
            if kind == "tracks":
                return [SPOTIFY_TRACK]
            return [{"name": "Matchbox Twenty", "genres": ["rock"], "images": [{"url": "https://i.scdn.co/a.jpg"}],
                     "external_urls": {"spotify": "https://open.spotify.com/artist/1"}}]

        with mock.patch.object(spotify.SpotifyClient, "top", top):
            response = self.client.get(reverse("hub:listening"), {"range": "long_term"})
        self.assertContains(response, "3AM")
        self.assertContains(response, "Matchbox Twenty")
        self.assertContains(response, "All time")

    def test_requests_the_chosen_period(self):
        self.connect()
        reply = mock.Mock(status_code=200, json=lambda: {"items": []})
        with mock.patch("hub.spotify.requests.get", return_value=reply) as get:
            spotify.SpotifyClient().top("t", "artists", "medium_term")
        self.assertIn("me/top/artists", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["params"]["time_range"], "medium_term")

    def test_spotify_being_down(self):
        self.connect()
        with mock.patch.object(spotify.SpotifyClient, "top", side_effect=requests.ConnectionError("down")):
            self.assertContains(self.client.get(reverse("hub:listening")), "did not respond")


class AboutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def about(self):
        repos = [
            {"name": "mine", "html_url": "https://github.com/x/mine", "description": "My repo", "language": "Python", "fork": False},
            {"name": "forked", "html_url": "https://github.com/x/forked", "fork": True},
        ]
        with mock.patch.object(AboutModule, "client_class") as client:
            client.return_value.repos.return_value = repos
            return self.client.get(reverse("hub:about"))

    def test_shows_the_profile_and_projects(self):
        Profile.objects.all().delete()
        Profile.objects.create(name="Pat", headline="Builder of things", bio="Hello there.")
        Project.objects.create(title="Thing", tech="Python, Django", url="https://example.com")
        response = self.about()
        for text in ("Pat", "Builder of things", "Hello there.", "Thing", "Django"):
            self.assertContains(response, text)

    def test_skips_forks(self):
        response = self.about()
        self.assertContains(response, "My repo")
        self.assertNotContains(response, "forked")

    def test_github_being_down_only_hides_that_section(self):
        with mock.patch.object(AboutModule, "client_class") as client:
            client.return_value.repos.side_effect = requests.ConnectionError("down")
            response = self.client.get(reverse("hub:about"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Recently on GitHub")

    def test_owner_is_told_when_the_bio_is_empty(self):
        self.client.force_login(staff_user())
        self.assertContains(self.about(), "Add it in the admin")


class BratPageTests(TestCase):
    def test_describes_the_add_on_and_links_its_code(self):
        response = self.client.get(reverse("hub:brat"))
        for text in ("Rotation Assistant", "Warcraft Logs", "Learn from Blizzard", "https://github.com/bmfelix/BRAT"):
            self.assertContains(response, text)

    def test_in_the_menu_not_on_the_homepage(self):
        response = self.client.get(reverse("hub:todo"))
        self.assertContains(response, f'href="{reverse("hub:brat")}"')
        self.assertFalse(BratModule.on_home)


class BuiltPageTests(TestCase):
    def test_compares_the_three_builds(self):
        response = self.client.get(reverse("hub:built"))
        for text in ("Channels", "Payload CMS", "Reverb", "daily-hub-laravel"):
            self.assertContains(response, text)

    def test_linked_from_the_footer_not_the_menu(self):
        response = self.client.get(reverse("hub:about"))
        self.assertContains(response, f'<a href="{reverse("hub:built")}">How it')


class LoginLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("owner", password="right-password")
        self.url = reverse("admin:login")

    def attempt(self, password):
        return self.client.post(self.url, {"username": "owner", "password": password})

    def test_locks_after_five_wrong_passwords(self):
        for _ in range(5):
            self.attempt("wrong")
        response = self.attempt("right-password")
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_right_password_works_before_the_limit(self):
        for _ in range(3):
            self.attempt("wrong")
        self.assertEqual(self.attempt("right-password").status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_a_good_login_clears_the_count(self):
        for _ in range(3):
            self.attempt("wrong")
        self.attempt("right-password")
        self.client.logout()
        for _ in range(3):
            self.attempt("wrong")
        self.assertEqual(self.attempt("right-password").status_code, 302)


@override_settings(REQUIRE_LOGIN=False, CALENDAR_URLS=[])
class NoLoginTests(TestCase):
    def test_pages_still_cannot_change_anything(self):
        self.assertEqual(self.client.post(reverse("hub:todo"), {"action": "add", "title": "Open"}).status_code, 405)
        self.assertEqual(self.client.post(reverse("hub:notes"), {"title": "Open"}).status_code, 405)
        self.assertFalse(Task.objects.exists())
        self.assertFalse(Note.objects.exists())

    def test_anyone_can_see_the_agenda(self):
        self.assertEqual(self.client.get(reverse("hub:agenda")).status_code, 200)
        with mock.patch.object(RadioModule, "stations", []):
            self.assertContains(self.client.get(reverse("hub:home")), reverse("hub:agenda"))

    def test_the_admin_still_needs_a_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_the_menu_has_no_admin_or_login_link(self):
        with mock.patch.object(RadioModule, "stations", []):
            response = self.client.get(reverse("hub:home"))
        self.assertNotContains(response, reverse("admin:index"))


class BuiltSiteLinkTests(TestCase):
    @override_settings(SITE_URLS={"django": "https://one.test", "nextjs": "https://two.test", "laravel": ""})
    def test_headings_link_to_each_live_site(self):
        response = self.client.get(reverse("hub:built"))
        self.assertContains(response, '<a href="https://one.test">Django</a>')
        self.assertContains(response, '<a href="https://two.test">Next.js</a>')
        self.assertContains(response, '<th scope="col">Laravel</th>')
