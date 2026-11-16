"""Jonli reyting: Redis sorted set (tezlik uchun), Redis bo'lmasa DB'dan hisoblanadi."""
import logging

from django.conf import settings

from .models import Participant

log = logging.getLogger(__name__)

COUNTED = (
    Participant.Status.WAITING,
    Participant.Status.ACTIVE,
    Participant.Status.FINISHED,
)


def _key(room_id):
    return f"lb:{room_id}"


def _redis():
    if getattr(settings, "RANKING_BACKEND", "redis") != "redis":
        return None
    try:
        from django_redis import get_redis_connection

        return get_redis_connection("default")
    except Exception:  # pragma: no cover
        return None


def update(p):
    """O'quvchining balini sorted set'ga yozadi."""
    conn = _redis()
    if not conn:
        return
    try:
        if p.status in COUNTED:
            conn.zadd(_key(p.room_id), {str(p.id): p.score})
        else:
            conn.zrem(_key(p.room_id), str(p.id))
    except Exception as e:
        log.warning("Redis reyting yangilanmadi: %s", e)


def rebuild(room):
    conn = _redis()
    if not conn:
        return
    try:
        conn.delete(_key(room.id))
        data = {
            str(i): s
            for i, s in Participant.objects.filter(room=room, status__in=COUNTED).values_list(
                "id", "score"
            )
        }
        if data:
            conn.zadd(_key(room.id), data)
    except Exception as e:
        log.warning("Redis reyting qayta qurilmadi: %s", e)


def _db_order(room):
    return Participant.objects.filter(room=room, status__in=COUNTED).order_by("-score", "joined_at")


def rank_of(p):
    if p.status not in COUNTED:
        return None
    conn = _redis()
    if conn:
        try:
            r = conn.zrevrank(_key(p.room_id), str(p.id))
            if r is not None:
                # teng ballar bir xil o'rin oladi
                higher = conn.zcount(_key(p.room_id), f"({p.score}", "+inf")
                return int(higher) + 1
        except Exception as e:
            log.warning("Redis rank xatosi: %s", e)
    return _db_order(p.room).filter(score__gt=p.score).count() + 1


def _card(p, rank):
    return {
        "id": p.id,
        "name": f"{p.first_name} {p.last_name}",
        "avatar": p.avatar,
        "score": p.score,
        "rank": rank,
        "school_class": p.school_class.name,
    }


def top(room, n=5):
    ids = None
    conn = _redis()
    if conn:
        try:
            raw = conn.zrevrange(_key(room.id), 0, n - 1)
            ids = [int(x) for x in raw]
        except Exception as e:
            log.warning("Redis top xatosi: %s", e)
    if ids:
        by_id = {
            p.id: p
            for p in Participant.objects.filter(id__in=ids, status__in=COUNTED).select_related(
                "school_class"
            )
        }
        ordered = sorted((by_id[i] for i in ids if i in by_id), key=lambda p: -p.score)
    else:
        ordered = list(_db_order(room).select_related("school_class")[:n])
    res, prev, rank = [], None, 0
    for idx, p in enumerate(ordered, start=1):
        if p.score != prev:
            rank, prev = idx, p.score
        res.append(_card(p, rank))
    return res


def standings(room):
    """Hamma hisobga olinadigan o'quvchilar tartibda (o'qituvchi paneli uchun)."""
    res, prev, rank = [], None, 0
    for idx, p in enumerate(_db_order(room).select_related("school_class"), start=1):
        if p.score != prev:
            rank, prev = idx, p.score
        res.append((p, rank))
    return res
