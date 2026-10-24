import time

from django.core.management.base import BaseCommand

from hub.listener import RadioListener
from hub.musicbrainz import ArtistLibrary


class Command(BaseCommand):
    help = "Check the radio stations on a timer and broadcast song changes to open homepages."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=15, help="Seconds between checks (default 15).")

    def handle(self, *args, interval, **options):
        listener = RadioListener()
        library = ArtistLibrary()
        announced = set()
        self.stdout.write(f"Listening for song changes every {interval:g} seconds.")
        while True:
            try:
                if listener.check():
                    self.stdout.write(f"Broadcast: {listener.last_seen}")
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
            time.sleep(interval)
