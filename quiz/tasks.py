from celery import shared_task
from django.utils import timezone


@shared_task
def finish_room_task(room_id):
    """Taymer tugaganda hamma o'quvchining testini avtomatik topshiradi."""
    from rooms.models import Room

    from . import services

    room = Room.objects.filter(pk=room_id).first()
    if not room or room.status != Room.Status.RUNNING:
        return "skip"
    if room.ends_at <= timezone.now():
        services.finish_room(room_id, manual=False)
        return "finished"
    services.schedule_finish(room)  # vaqt uzaytirilgan bo'lsa qayta rejalashtiriladi
    return "rescheduled"


@shared_task
def unfreeze_task(participant_id):
    """Muzlatish tugaganda o'quvchi ekranini yangilaydi."""
    from . import events

    events.refresh_participant(participant_id)
