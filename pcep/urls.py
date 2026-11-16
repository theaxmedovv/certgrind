from django.urls import path

from . import views

app_name = "pcep"
urlpatterns = [
    path("", views.home, name="home"),
    path("start/<str:kind>/", views.start, name="start"),
    path("attempt/<int:attempt_id>/", views.attempt_view, name="attempt"),
    path("attempt/<int:attempt_id>/save/", views.save, name="save"),
    path("attempt/<int:attempt_id>/finish/", views.finish, name="finish"),
    path("attempt/<int:attempt_id>/result/", views.result, name="result"),
    path("attempt/<int:attempt_id>/review/", views.review, name="review"),
    path("attempt/<int:attempt_id>/retry/", views.retry_mistakes, name="retry"),
    path("stats/", views.stats, name="stats"),
]
