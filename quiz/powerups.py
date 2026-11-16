"""Maxfiy kod super-kuchlari (tasodifiy rejim).

O'quvchi faqat kuch TURINI tanlaydi. Nishon va miqdor/vaqt SERVERDA `secrets` bilan tasodifiy
tanlanadi; hisob-kitob transaction.atomic + select_for_update bilan (parallel hujumlarda xato bo'lmaydi).
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import events, ranking
from .models import Participant, PowerUpCode, PowerUpLog
from .services import GameError, P, R, _has_pending_violation, _is_frozen, schedule_unfreeze

REEL_SIZE = 12  # baraban animatsiyasi uchun ko'rsatiladigan avatarlar soni (nishon shu ichida)


class _Retry(Exception):
    """Tanlangan nishon qulflangach yaroqsiz bo'lib qoldi: boshqasini tanlaymiz."""


def _range(lo, hi):
    lo, hi = int(lo), int(hi)
    return (lo, hi) if lo <= hi else (hi, lo)


def eligible_targets(att, kind, now=None):
    """Nishon bo'la oladigan o'quvchilar: faqat FAOL. O'zi, chetlatilgan (qoidabuzar), kutayotgan,
    muzlatilgan, testni tugatgan va hujumchining oxirgi nishoni hisobga olinmaydi."""
    now = now or timezone.now()
    pending = set(
        Participant.objects.filter(room_id=att.room_id, violations__decision="pending").values_list("id", flat=True)
    )
    out = []
    for p in Participant.objects.filter(room_id=att.room_id, status=P.ACTIVE).exclude(pk=att.pk).select_related("school_class"):
        if p.id in pending or _is_frozen(p, now) or p.id == att.last_target_id:
            continue
        if kind == "steal" and p.score <= 0:
            continue  # ballsiz o'quvchidan o'g'irlash befoyda: nishon bo'lmaydi
        out.append(p)
    return out


def use_powerup(attacker_id, code, kind):
    if kind not in ("steal", "freeze"):
        raise GameError("value", "Noto'g'ri super-kuch")
    for _ in range(6):
        att = Participant.objects.select_related("room").get(pk=attacker_id)
        if att.status != P.ACTIVE or _has_pending_violation(att):
            raise GameError("state", "Siz hozir super-kuch ishlata olmaysiz")
        if _is_frozen(att):
            raise GameError("frozen", "Ekraningiz muzlagan")
        cands = eligible_targets(att, kind)
        if not cands:
            # kod yo'qolmaydi: faqat xabar
            raise GameError(
                "no_target",
                "Hozir nishon bo'ladigan faol o'quvchi yo'q. Maxfiy kodingiz saqlanib qoldi — keyinroq urinib ko'ring.",
            )
        victim = secrets.choice(cands)
        reel = [c for c in cands if c.id != victim.id]
        secrets.SystemRandom().shuffle(reel)
        reel = reel[: REEL_SIZE - 1] + [victim]
        secrets.SystemRandom().shuffle(reel)
        try:
            return _apply(attacker_id, victim.id, code, kind, reel)
        except _Retry:
            continue
    raise GameError("no_target", "Hozir nishon bo'ladigan faol o'quvchi yo'q. Maxfiy kodingiz saqlanib qoldi.")


def _apply(attacker_id, victim_id, code, kind, reel):
    now = timezone.now()
    with transaction.atomic():
        locked = {
            p.id: p
            for p in Participant.objects.select_for_update()
            .select_related("room", "school_class")
            .filter(id__in=sorted({attacker_id, victim_id}))
            .order_by("id")
        }
        att, vic = locked.get(attacker_id), locked.get(victim_id)
        if not att or not vic or att.room_id != vic.room_id:
            raise GameError("none", "Nishon topilmadi")
        room = att.room
        if not room.powerups_enabled or not getattr(room, f"{kind}_enabled"):
            raise GameError("disabled", "Bu super-kuch o'chirilgan")
        if room.status != R.RUNNING:
            raise GameError("state", "Test hozir ishlamayapti")
        if att.status != P.ACTIVE or _has_pending_violation(att):
            raise GameError("state", "Siz hozir super-kuch ishlata olmaysiz")
        if _is_frozen(att, now):
            raise GameError("frozen", "Ekraningiz muzlagan")
        pc = (
            PowerUpCode.objects.select_for_update()
            .filter(participant=att, code=(code or "").strip().upper())
            .first()
        )
        if not pc or pc.is_used:
            raise GameError("code", "Maxfiy kod yaroqsiz")
        # nishon qulflangach holati o'zgargan bo'lishi mumkin -> qayta tanlaymiz
        if (
            vic.status != P.ACTIVE
            or _has_pending_violation(vic)
            or att.last_target_id == vic.id
            or _is_frozen(vic, now)
            or (kind == "steal" and vic.score <= 0)
        ):
            raise _Retry()
        amount, seconds = 0, 0
        if kind == "steal":
            lo, hi = _range(room.steal_min_percent, room.steal_max_percent)
            pct = lo + secrets.randbelow(hi - lo + 1)
            amount = min(vic.score, max(1, vic.score * pct // 100))  # ball manfiy bo'lmaydi
            vic.score -= amount
            att.score += amount
            vic.save(update_fields=["score"])
        else:
            lo, hi = _range(room.freeze_min_seconds, room.freeze_max_seconds)
            seconds = lo + secrets.randbelow(hi - lo + 1)
            vic.frozen_until = now + timedelta(seconds=seconds)
            vic.save(update_fields=["frozen_until"])
        att.last_target = vic
        att.save(update_fields=["score", "last_target"])
        pc.is_used = True
        pc.used_at = now
        pc.save(update_fields=["is_used", "used_at"])
        PowerUpLog.objects.create(
            room=room, attacker=att, victim=vic, type=kind, points_amount=amount, freeze_seconds=seconds
        )
    ranking.update(att)
    ranking.update(vic)
    aname = att.first_name
    if kind == "steal":
        text = f"💰 {aname} sendan {amount} ball oldi!"
    else:
        text = f"❄️ {aname} seni {seconds} soniyaga muzlatdi!"
        schedule_unfreeze(vic)
    events.notice(vic.id, kind=kind, text=text, amount=amount, seconds=seconds, attacker=aname)
    events.refresh_participant(vic.id)
    events.teacher_update(room)
    att.refresh_from_db()
    lo, hi = _range(room.steal_min_percent, room.steal_max_percent) if kind == "steal" else _range(
        room.freeze_min_seconds, room.freeze_max_seconds
    )
    return {
        "t": "powerup_result",
        "kind": kind,
        "amount": amount,
        "seconds": seconds,
        "range": [lo, hi],
        "victim": f"{vic.first_name} {vic.last_name}",
        "target": {"id": vic.id, "name": f"{vic.first_name} {vic.last_name}", "avatar": vic.avatar},
        "reel": [{"id": r.id, "name": r.first_name, "avatar": r.avatar} for r in reel],
        "score": att.score,
        "codes": list(
            PowerUpCode.objects.filter(participant=att, is_used=False).values_list("code", flat=True)
        ),
    }
