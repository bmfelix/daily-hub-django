from django.urls import path

from . import views
from .modules import MODULES

app_name = "hub"

urlpatterns = [
    path("", views.home, name="home"),
    *[path(f"{module.slug}/", module.as_view(), name=module.slug) for module in MODULES],
]
