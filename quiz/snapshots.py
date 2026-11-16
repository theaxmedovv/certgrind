"""O'qituvchi paneli uchun to'liq holat (snapshot)."""
from django.db.models import Count, Q
from django.utils import timezone

from rooms.models import Room

from . import ranking, timer
from .models import Participant, PowerUpLog, Violation


def _t(dt, fmt="%H:%M:%S"):
    return timezone.localtime(dt).strftime(fmt) if dt else ""


def pname(p):
    return f"{p.first_name} {p.last_name}"


def projector_snapshot(room):
    """Proyektor uchun yengillashtirilgan holat: qoidabuzarlik/kech kirish so'rovlari yo'q."""
    snap = teacher_snapshot(room)
    keep = ("id", "name", "school_class", "avatar", "status", "score", "rank", "answered", "correct", "frozen", "streak", "round", "in_round")
    snap["participants"] = [
        {k: p[k] for k in keep} | {"is_late": False, "violations": 0, "locked": False}
        for p in snap["participants"]
    ]
    snap["violations"] = []
    snap["late"] = []
    snap["powerups"] = snap["powerups"][:30]
    snap["room"] = snap["room"] | {"results_visible": False}
    return snap


def teacher_snapshot(room):
    room = Room.objects.get(pk=room.pk)
    now = timezone.now()
    total_q = room.room_questions.count()
    parts = list(
        Participant.objects.filter(room=room)
        .select_related("school_class")
        .annotate(
            correct=Count("answers", filter=Q(answers__is_correct=True), distinct=True),
            answered=Count("answers", distinct=True),
            vcount=Count("violations", distinct=True),
        )
    )
    rank_map = {p.id: r for p, r in ranking.standings(room)}
    pending_v = set(
        Violation.objects.filter(participant__room=room, decision="pending").values_list(
            "participant_id", flat=True
        )
    )
    plist = []
    for p in parts:
        plist.append(
            {
                "id": p.id,
                "name": pname(p),
                "first_name": p.first_name,
                "last_name": p.last_name,
                "school_class": p.school_class.name,
                "avatar": p.avatar,
                "status": p.status,
                "is_late": p.is_late,
                "score": p.score,
                "rank": rank_map.get(p.id),
                "round": p.current_round if p.status in ("active", "finished") else 0,
                "in_round": max(0, p.current_index - (p.current_round - 1) * total_q) if p.status == "active" else 0,
                "answered": p.answered,
                "correct": p.correct,
                "violations": p.vcount,
                "locked": p.id in pending_v,
                "frozen": bool(p.frozen_until and p.frozen_until > now),
                "streak": p.streak,
                "extra_seconds": p.extra_seconds,
            }
        )
    plist.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0, x["id"]))

    viol = (
        Violation.objects.filter(participant__room=room)
        .select_related("participant__school_class")
        .order_by("-occurred_at")[:200]
    )
    vcount = {p.id: p.vcount for p in parts}
    violations = [
        {
            "id": v.id,
            "pid": v.participant_id,
            "name": pname(v.participant),
            "school_class": v.participant.school_class.name,
            "type": v.type,
            "type_label": v.get_type_display(),
            "time": _t(v.occurred_at),
            "decision": v.decision,
            "count": vcount.get(v.participant_id, 0),
        }
        for v in viol
    ]
    late = [
        {
            "pid": p.id,
            "name": pname(p),
            "school_class": p.school_class.name,
            "avatar": p.avatar,
            "time": _t(p.joined_at, "%H:%M"),
        }
        for p in parts
        if p.status == Participant.Status.PENDING
    ]
    logs = PowerUpLog.objects.filter(room=room).select_related(
        "attacker__school_class", "victim__school_class"
    )[:100]
    powerups = [
        {
            "attacker": pname(l.attacker),
            "victim": pname(l.victim),
            "type": l.type,
            "amount": l.points_amount,
            "seconds": l.freeze_seconds,
            "time": _t(l.created_at),
        }
        for l in logs
    ]
    return {
        "t": "snapshot",
        "server_now": now.timestamp(),
        "room": {
            "id": room.id,
            "name": room.name,
            "code": room.code,
            "status": room.status,
            "remaining": timer.room_remaining(room, now),
            "duration": room.duration_minutes * 60,
            "total_questions": total_q,
            "results_visible": room.results_visible,
            "powerups_enabled": room.powerups_enabled,
        },
        "participants": plist,
        "violations": violations,
        "late": late,
        "powerups": powerups,
        "podium": ranking.top(room, 3) if room.status == Room.Status.FINISHED else [],
    }
