"""Server vaqti asosidagi umumiy taymer. Mijoz soatiga ishonilmaydi."""
from datetime import timedelta

from django.utils import timezone

from rooms.models import Room


def room_remaining(room, at=None):
    """Xonada qolgan soniyalar (float)."""
    at = at or timezone.now()
    if room.status == Room.Status.WAITING:
        return float(room.duration_minutes * 60)
    if room.status == Room.Status.FINISHED or not room.ends_at:
        return 0.0
    ref = room.paused_at if (room.status == Room.Status.PAUSED and room.paused_at) else at
    return max(0.0, (room.ends_at - ref).total_seconds())


def participant_deadline(room, participant):
    """O'quvchi uchun yakuniy muddat (umumiy tugash + shaxsiy qo'shimcha)."""
    if not room.ends_at:
        return None
    return room.ends_at + timedelta(seconds=participant.extra_seconds or 0)


def participant_remaining(room, participant, at=None):
    at = at or timezone.now()
    if room.status == Room.Status.FINISHED:
        dl = participant_deadline(room, participant)
        if dl and participant.extra_seconds:
            return max(0.0, (dl - at).total_seconds())
        return 0.0
    return room_remaining(room, at) + (participant.extra_seconds or 0)
