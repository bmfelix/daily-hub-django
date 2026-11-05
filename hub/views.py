import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from . import spotify
from .models import Artist, Song, SpotifyAccount
from .modules import visible_modules
from .music import MusicClient
from .musicbrainz import ArtistLibrary, artist_profile

UNAVAILABLE = "MusicBrainz did not respond. Try again shortly."
SPOTIFY_STATE_SALT = "hub.spotify"
SPOTIFY_STATE_MINUTES = 10


def home(request):
    cards = [
        {"module": module, "template": module.card_template, **module.card()}
        for module in visible_modules(request.user) if module.on_home
    ]
    return render(request, "hub/home.html", {"cards": cards, "playlists": spotify.playlist_embed_urls()})


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
    if artist.extras_checked_at is None and not artist.locked:
        ArtistLibrary().add_extras(artist)
    return render(request, "hub/artist.html", {"artist": artist_profile(artist)})


def song_preview(request, pk):
    """Send the audio player to a preview. Deezer's addresses expire, so each is fetched as it is played."""
    song = get_object_or_404(Song, pk=pk)
    if song.apple_preview_url:
        return redirect(song.apple_preview_url)
    if song.deezer_track_id:
        try:
            url = MusicClient().deezer_preview(song.deezer_track_id)
        except requests.RequestException:
            return HttpResponse("The preview service did not respond.", status=503)
        if url:
            return redirect(url)
    raise Http404("This song has no preview.")


def spotify_card(request):
    """What the homepage's Spotify panel shows. The page asks for this after it opens."""
    context = {"configured": spotify.is_configured()}
    try:
        context["track"] = spotify.listening()
    except requests.RequestException:
        context["error"] = "Spotify did not respond. Try again shortly."
    return render(request, "hub/cards/spotify_live.html", context)


@staff_member_required
def spotify_connect(request):
    """Send the site owner to Spotify to allow access."""
    if not spotify.is_configured():
        return HttpResponseBadRequest("Add your Spotify app's ID and secret to .env first.")
    state = signing.dumps("connect", salt=SPOTIFY_STATE_SALT)
    return redirect(spotify.SpotifyClient().authorize_url(state))


def spotify_callback(request):
    """Spotify returns here. The return address is 127.0.0.1, where the login cookie may not exist,
    so the signed state shows this began in spotify_connect instead."""
    try:
        signing.loads(request.GET.get("state", ""), salt=SPOTIFY_STATE_SALT, max_age=SPOTIFY_STATE_MINUTES * 60)
    except signing.BadSignature:
        return HttpResponseBadRequest("This Spotify link has expired. Start again from the homepage.")
    code = request.GET.get("code")
    if not code:
        return redirect("hub:home")  # access was refused
    try:
        tokens = spotify.SpotifyClient().exchange_code(code)
    except requests.RequestException:
        return HttpResponse("Spotify did not respond. Try connecting again.", status=503)
    SpotifyAccount.objects.all().delete()
    spotify.save_tokens(SpotifyAccount(), tokens)
    return redirect("hub:home")
