from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/student/", consumers.StudentConsumer.as_asgi()),
    path("ws/teacher/<int:room_id>/", consumers.TeacherConsumer.as_asgi()),
    path("ws/projector/<int:room_id>/", consumers.ProjectorConsumer.as_asgi()),
]
