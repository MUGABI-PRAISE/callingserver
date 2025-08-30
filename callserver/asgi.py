"""
ASGI config for callserver project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

# initialize the app early enough before other things like querying the database/models is done
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")


from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import server.routing  


application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            server.routing.websocket_urlpatterns
        )
    ),
})

