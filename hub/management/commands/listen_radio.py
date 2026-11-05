import time

from django.core.management.base import BaseCommand

from hub.listener import RadioListener
from hub.modules.radio import RadioModule
from hub.music import SongLibrary
from hub.musicbrainz import ArtistLibrary

SONGS_PER_CHECK = 3  # Apple allows about 20 requests a minute


class Command(BaseCommand):
    help = "Check the radio stations on a timer and broadcast song changes to open homepages."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=15, help="Seconds between checks (default 15).")

    def handle(self, *args, interval, **options):
        listener = RadioListener()
        library = ArtistLibrary()
        songs = SongLibrary()
        waiting_songs = {}
        announced = set()
        self.stdout.write(f"Listening for song changes every {interval:g} seconds.")
        while True:
            try:
                if listener.check():
                    self.stdout.write(f"Broadcast: {listener.last_seen}")
                    waiting_songs.update(dict.fromkeys(RadioModule.remember_recent()))
            except Exception as error:  # keep listening through any one bad check
                self.stderr.write(f"Check failed: {error!r}")
            # Look up new artists now, so their pages open instantly. Saved ones cost only a database read.
            for name in listener.current_artists():
                try:
                    artist = library.find(name)
                    if name not in announced:
                        announced.add(name)
                        self.stdout.write(f"Artist ready: {name} -> {artist or 'no match'}")
                except Exception as error:
                    self.stderr.write(f"Artist lookup failed for {name!r}: {error!r}")
            self.look_up_songs(songs, waiting_songs)
            time.sleep(interval)

    def look_up_songs(self, library, waiting):
        """Look up a few waiting songs. The rest stay waiting for the next check."""
        for artist, title in list(waiting)[:SONGS_PER_CHECK]:
            del waiting[(artist, title)]
            try:
                library.find(artist, title)
            except Exception as error:  # one bad song must not stop the listener
                self.stderr.write(f"Song lookup failed for {artist!r} {title!r}: {error!r}")
