"""Channels guruhlariga xabar yuborish (sinxron kodlardan chaqiriladi)."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache

log = logging.getLogger(__name__)


def _group_send(group, msg):
    try:
        async_to_sync(get_channel_layer().group_send)(group, msg)
    except Exception as e:  # Redis ishlamasa o'yin mantig'i buzilmasin
        log.warning("group_send xatosi (%s): %s", group, e)


def teacher_group(room_id):
    return f"room_{room_id}_teacher"


def students_group(room_id):
    return f"room_{room_id}_students"


def projector_group(room_id):
    return f"room_{room_id}_projector"


def participant_group(pid):
    return f"participant_{pid}"


def refresh_students(room_id):
    _group_send(students_group(room_id), {"type": "ws.refresh"})


def refresh_participant(pid):
    _group_send(participant_group(pid), {"type": "ws.refresh"})


def notice(pid, **data):
    _group_send(participant_group(pid), {"type": "ws.send", "payload": {"t": "notice", **data}})


def teacher_update(room, alert=None, throttle=False):
    """O'qituvchiga yangi snapshot yuboradi. alert -> ovozli signal uchun."""
    from . import snapshots

    if throttle:
        try:
            if not cache.add(f"tsnap:{room.id}", 1, 1):
                return
        except Exception:
            pass
    snap = snapshots.teacher_snapshot(room)
    if alert:
        snap["alert"] = alert
    _group_send(teacher_group(room.id), {"type": "ws.send", "payload": snap})
    _group_send(projector_group(room.id), {"type": "ws.send", "payload": snapshots.projector_snapshot(room)})
