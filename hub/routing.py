from django.urls import path

from .consumers import RadioConsumer

websocket_urlpatterns = [
    path("ws/radio/", RadioConsumer.as_asgi()),
]
