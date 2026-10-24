from django.urls import path

from . import views
from .modules import MODULES

app_name = "hub"

urlpatterns = [
    path("", views.home, name="home"),
    path("artists/", views.artist_lookup, name="artist_lookup"),
    path("artists/<uuid:mbid>/", views.artist_detail, name="artist"),
    *[path(f"{module.slug}/", module.as_view(), name=module.slug) for module in MODULES],
]
