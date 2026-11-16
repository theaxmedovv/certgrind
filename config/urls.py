from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("panel/", include("rooms.urls")),
    path("panel/", include("questions.urls")),
    path("panel/", include("stats.urls")),
    path("pcep/", include("pcep.urls")),
    path("", include("quiz.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
