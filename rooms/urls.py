from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("xonalar/", views.room_list, {"mode": "rooms"}, name="room_list"),
    path("natijalar/", views.room_list, {"mode": "results"}, name="results_list"),
    path("statistika/", views.room_list, {"mode": "stats"}, name="stats_list"),
    path("xonalar/yangi/", views.room_create, name="room_create"),
    path("xonalar/<int:pk>/", views.room_control, name="room_control"),
    path("xonalar/<int:pk>/tayyor/", views.room_ready, name="room_ready"),
    path("xonalar/<int:pk>/ekran/", views.room_screen, name="room_screen"),
    path("xonalar/<int:pk>/qr.png", views.room_qr, name="room_qr"),
    path("xonalar/<int:pk>/natija-ruxsati/", views.room_results_visible, name="room_results_visible"),
    path("xonalar/<int:pk>/ochirish/", views.room_delete, name="room_delete"),
]
