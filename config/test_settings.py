from .settings import *  # noqa

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
RANKING_BACKEND = "db"
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
