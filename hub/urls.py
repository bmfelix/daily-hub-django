from django.urls import path

from . import views
from .modules import MODULES

app_name = "hub"

urlpatterns = [
    path("", views.home, name="home"),
    path("artists/", views.artist_lookup, name="artist_lookup"),
    path("artists/<uuid:mbid>/", views.artist_detail, name="artist"),
    path("songs/<int:pk>/preview/", views.song_preview, name="song_preview"),
    path("spotify/card/", views.spotify_card, name="spotify_card"),
    path("spotify/connect/", views.spotify_connect, name="spotify_connect"),
    path("spotify/callback/", views.spotify_callback, name="spotify_callback"),
    *[path(f"{module.slug}/", module.as_view(), name=module.slug) for module in MODULES],
]
