from django.urls import path

from . import views

urlpatterns = [
    path("statistika/toplamlar/", views.sets_stats, name="sets_stats"),
    path("xonalar/<int:pk>/natijalar/", views.results, name="results"),
    path("xonalar/<int:pk>/natijalar.xlsx", views.results_export, name="results_export"),
    path("xonalar/<int:pk>/statistika/", views.room_stats, name="room_stats"),
]
