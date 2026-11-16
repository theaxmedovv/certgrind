import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

# Daphne'ni to'g'ridan-to'g'ri ishga tushirganda (runserver'siz) statik fayllar DEBUG'da shu yerdan beriladi.
# Ishlab chiqarishda collectstatic + nginx/whitenoise ishlatiladi.
from django.conf import settings  # noqa: E402

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

    django_asgi_app = ASGIStaticFilesHandler(django_asgi_app)

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from quiz.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
