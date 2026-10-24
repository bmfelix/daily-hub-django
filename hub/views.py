import requests
from django.http import Http404
from django.shortcuts import redirect, render

from .models import Artist
from .modules import MODULES
from .musicbrainz import ArtistLibrary, artist_profile

UNAVAILABLE = "MusicBrainz did not respond. Try again shortly."


def home(request):
    cards = [{"module": module, "template": module.card_template, **module.card()} for module in MODULES]
    return render(request, "hub/home.html", {"cards": cards})


def artist_lookup(request):
    """Open the artist page for a name as the radio spells it."""
    name = request.GET.get("name", "").strip()
    if not name:
        raise Http404("No artist name given.")
    try:
        artist = ArtistLibrary().find(name)
    except requests.RequestException:
        return render(request, "hub/artist_missing.html", {"name": name, "error": UNAVAILABLE}, status=503)
    if artist is None:
        return render(request, "hub/artist_missing.html", {"name": name}, status=404)
    return redirect("hub:artist", mbid=artist.mbid)


def artist_detail(request, mbid):
    """One artist. Band members and related artists link here too, so fetch any not yet saved."""
    artist = Artist.objects.filter(mbid=mbid).first()
    if artist is None:
        try:
            artist = ArtistLibrary().save(str(mbid))
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code in (400, 404):
                raise Http404("No such artist.") from error
            return render(request, "hub/artist_missing.html", {"error": UNAVAILABLE}, status=503)
        except requests.RequestException:
            return render(request, "hub/artist_missing.html", {"error": UNAVAILABLE}, status=503)
    return render(request, "hub/artist.html", {"artist": artist_profile(artist)})
