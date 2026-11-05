import time

import requests
from django.core.management.base import BaseCommand

from hub.models import Artist
from hub.musicbrainz import ArtistLibrary


class Command(BaseCommand):
    help = "Add Wikipedia text and Apple artwork to saved artists that do not have them yet."

    def add_arguments(self, parser):
        parser.add_argument("--delay", type=float, default=3.5, help="Seconds between artists (Apple allows about 20 requests a minute).")

    def handle(self, *args, delay, **options):
        library = ArtistLibrary()
        for artist in Artist.objects.filter(extras_checked_at=None, locked=False):
            library.add_extras(artist)
            status = "done" if artist.extras_checked_at else "will try again later"
            wikipedia = "Wikipedia" if artist.wikipedia_summary else "no Wikipedia"
            self.stdout.write(f"{artist}: {status}, {wikipedia}, {len(artist.apple_albums)} Apple albums")
            time.sleep(delay)
