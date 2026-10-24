"""
ASGI entry point. Normal pages go to Django; WebSocket connections go to Channels.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Load Django before importing anything that uses models or settings.
django_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from hub.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_application,
    "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
})
