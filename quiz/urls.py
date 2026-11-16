from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("kirish/<str:code>/", views.join_page, name="join"),
    path("api/join/", views.join_api, name="join_api"),
    path("play/", views.play, name="play"),
]
