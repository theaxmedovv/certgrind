"""O'yin mantig'i. Barcha muhim tekshiruvlar (javob, ball, vaqt) SERVERDA bajariladi."""
import logging
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from questions.models import SchoolClass
from rooms.models import Room, RoomEvent

from . import events, ranking, timer
from .models import Answer, Participant, ParticipantQuestion, PowerUpCode, Violation

log = logging.getLogger(__name__)

AVATARS = [f"a{i:02d}" for i in range(1, 25)]  # SVG avatar kalitlari (frontend: Avatar.svg)

MAX_POINTS = 1000
MIN_POINTS = 500
STREAK_TARGET = 3
MAX_UNUSED_CODES = 2

P = Participant.Status
R = Room.Status


class GameError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- ball
def calc_points(response_ms, scale_ms):
    """To'g'ri javob uchun ball: MAX dan MIN gacha vaqt o'tgani sayin kamayadi."""
    ratio = min(1.0, max(0.0, response_ms / max(scale_ms, 1)))
    return int(round(MAX_POINTS - (MAX_POINTS - MIN_POINTS) * ratio))


def question_scale_ms(room, total_q):
    secs = room.duration_minutes * 60 / max(total_q, 1)
    return int(min(60, max(10, secs)) * 1000)


# ---------------------------------------------------------------- yordamchilar
def schedule_finish(room):
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or not room.ends_at:
        return
    try:
        from .tasks import finish_room_task

        finish_room_task.apply_async(
            args=[room.id], eta=room.ends_at + timedelta(seconds=1), retry=False
        )
    except Exception as e:
        log.warning("Celery vazifasi rejalashtirilmadi: %s", e)


def schedule_unfreeze(p):
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or not p.frozen_until:
        return
    try:
        from .tasks import unfreeze_task

        unfreeze_task.apply_async(
            args=[p.id], eta=p.frozen_until + timedelta(seconds=1), retry=False
        )
    except Exception as e:
        log.warning("Celery vazifasi rejalashtirilmadi: %s", e)


def log_event(room, type_, **payload):
    RoomEvent.objects.create(room=room, type=type_, payload=payload)


def refresh_room_clock(room):
    """Vaqt tugagan bo'lsa xonani yakunlaydi (Celery'ga qo'shimcha xavfsizlik)."""
    if room.status == R.RUNNING and room.ends_at and room.ends_at <= timezone.now():
        finish_room(room.id, manual=False)
        room.refresh_from_db()
    return room


def _has_pending_violation(p):
    return Violation.objects.filter(participant=p, decision=Violation.Decision.PENDING).exists()


def _total_questions(room):
    return room.room_questions.count()


def _finish_participant(p, now=None):
    p.status = P.FINISHED
    p.finished_at = now or timezone.now()
    p.save(update_fields=["status", "finished_at"])
    ranking.update(p)


# ---------------------------------------------------------------- kirish
def join_room(code, password, first_name, last_name, class_id, avatar):
    code = (code or "").strip()
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    if not (first_name and last_name):
        raise GameError("name", "Ism va familiyani kiriting")
    if len(first_name) > 60 or len(last_name) > 60:
        raise GameError("name", "Ism yoki familiya juda uzun")
    room = Room.objects.filter(code=code).first()
    if not room or not room.check_password(password or ""):
        raise GameError("auth", "Xona raqami yoki parol noto'g'ri")
    school_class = SchoolClass.objects.filter(pk=class_id).first()
    if not school_class:
        raise GameError("class", "Sinfni tanlang")
    if avatar not in AVATARS:
        avatar = AVATARS[0]
    room = refresh_room_clock(room)
    if room.status == R.FINISHED:
        raise GameError("finished", "Bu test yakunlangan")
    late = room.status in (R.RUNNING, R.PAUSED)
    p = Participant.objects.create(
        room=room,
        first_name=first_name,
        last_name=last_name,
        school_class=school_class,
        avatar=avatar,
        status=P.PENDING if late else P.WAITING,
        is_late=late,
    )
    if late:
        log_event(room, "late_join", participant=p.id, name=str(p))
    ranking.update(p)
    alert = None
    if late:
        alert = {
            "kind": "late",
            "pid": p.id,
            "text": f"{p.first_name} {p.last_name} ({school_class.name}) testga kirmoqchi — "
            f"{timezone.localtime().strftime('%H:%M')}",
        }
    events.teacher_update(room, alert=alert)
    if not late:
        events.refresh_students(room.id)  # kutish xonasidagilar yangi o'quvchini ko'rsin
    return p


def get_participant_by_token(token):
    if not token:
        return None
    return Participant.objects.select_related("room", "school_class").filter(
        session_token=token
    ).first()


# ---------------------------------------------------------------- o'qituvchi boshqaruvi
def _lock_room(room_id):
    return Room.objects.select_for_update().get(pk=room_id)


def start_room(room_id):
    with transaction.atomic():
        room = _lock_room(room_id)
        if room.status != R.WAITING:
            raise GameError("state", "Test allaqachon boshlangan")
        if not room.room_questions.exists():
            raise GameError("empty", "Xonada savollar yo'q")
        now = timezone.now()
        room.status = R.RUNNING
        room.started_at = now
        room.ends_at = now + timedelta(minutes=room.duration_minutes)
        room.save(update_fields=["status", "started_at", "ends_at"])
        log_event(room, "start")
    ranking.rebuild(room)
    schedule_finish(room)
    events.refresh_students(room.id)
    events.teacher_update(room)
    return room


def pause_room(room_id):
    with transaction.atomic():
        room = _lock_room(room_id)
        if room.status != R.RUNNING:
            raise GameError("state", "Test ishlamayapti")
        room.status = R.PAUSED
        room.paused_at = timezone.now()
        room.save(update_fields=["status", "paused_at"])
        ParticipantQuestion.objects.filter(
            participant__room=room,
            participant__status=P.ACTIVE,
            position=F("participant__current_index"),
        ).update(shown_at=None)
        log_event(room, "pause")
    events.refresh_students(room.id)
    events.teacher_update(room)
    return room


def resume_room(room_id):
    with transaction.atomic():
        room = _lock_room(room_id)
        if room.status != R.PAUSED:
            raise GameError("state", "Test pauzada emas")
        now = timezone.now()
        delta = now - room.paused_at
        room.ends_at = room.ends_at + delta
        room.total_paused_seconds += int(delta.total_seconds())
        Participant.objects.filter(room=room, frozen_until__gt=room.paused_at).update(
            frozen_until=F("frozen_until") + delta
        )
        room.paused_at = None
        room.status = R.RUNNING
        room.save(update_fields=["ends_at", "total_paused_seconds", "paused_at", "status"])
        log_event(room, "resume")
    schedule_finish(room)
    events.refresh_students(room.id)
    events.teacher_update(room)
    return room


def add_time(room_id, seconds):
    seconds = int(seconds)
    if seconds <= 0 or seconds > 6 * 3600:
        raise GameError("value", "Noto'g'ri vaqt")
    with transaction.atomic():
        room = _lock_room(room_id)
        if room.status not in (R.RUNNING, R.PAUSED):
            raise GameError("state", "Test ishlamayapti")
        room.ends_at = room.ends_at + timedelta(seconds=seconds)
        room.save(update_fields=["ends_at"])
        log_event(room, "add_time", seconds=seconds)
    schedule_finish(room)
    events.refresh_students(room.id)
    events.teacher_update(room)
    return room


def finish_room(room_id, manual=True):
    with transaction.atomic():
        room = _lock_room(room_id)
        if room.status == R.FINISHED:
            return room
        if room.status == R.WAITING:
            raise GameError("state", "Test hali boshlanmagan")
        now = timezone.now()
        if manual:
            room.ends_at = now
        room.paused_at = None
        room.status = R.FINISHED
        room.save(update_fields=["status", "ends_at", "paused_at"])
        if manual:
            room.participants.update(extra_seconds=0)
        # vaqt tugaganda shaxsiy qo'shimcha vaqti bor faol o'quvchilar davom etadi
        qs = room.participants.filter(status__in=[P.WAITING, P.ACTIVE])
        for p in qs:
            if p.status == P.ACTIVE and p.extra_seconds and not manual:
                continue
            _finish_participant(p, now)
        room.participants.filter(status=P.PENDING).update(status=P.KICKED)
        log_event(room, "finish", manual=manual)
    ranking.rebuild(room)
    events.refresh_students(room.id)
    events.teacher_update(room)
    return room


def set_results_visible(room_id, value):
    Room.objects.filter(pk=room_id).update(results_visible=bool(value))
    room = Room.objects.get(pk=room_id)
    events.refresh_students(room.id)
    events.teacher_update(room)


def kick_participant(room_id, pid):
    p = Participant.objects.filter(room_id=room_id, pk=pid).first()
    if not p:
        raise GameError("none", "O'quvchi topilmadi")
    p.status = P.KICKED
    p.save(update_fields=["status"])
    ranking.update(p)
    events.refresh_participant(p.id)
    events.teacher_update(p.room)


def decide_late(room_id, pid, allow, extra_seconds=0):
    with transaction.atomic():
        p = Participant.objects.select_for_update().filter(room_id=room_id, pk=pid).first()
        if not p or p.status != P.PENDING:
            raise GameError("none", "So'rov topilmadi")
        room = Room.objects.get(pk=room_id)
        if allow and room.status == R.FINISHED:
            allow = False
        if allow:
            p.status = P.WAITING
            p.extra_seconds = max(0, min(int(extra_seconds or 0), 3600))
        else:
            p.status = P.KICKED
        p.save(update_fields=["status", "extra_seconds"])
    ranking.update(p)
    events.refresh_participant(p.id)
    events.teacher_update(room)


def give_extra_time(room_id, pid, seconds):
    seconds = int(seconds)
    if seconds <= 0 or seconds > 3600:
        raise GameError("value", "Noto'g'ri vaqt")
    p = Participant.objects.filter(room_id=room_id, pk=pid).first()
    if not p:
        raise GameError("none", "O'quvchi topilmadi")
    Participant.objects.filter(pk=p.pk).update(extra_seconds=F("extra_seconds") + seconds)
    events.refresh_participant(p.id)
    events.teacher_update(p.room)


# ---------------------------------------------------------------- o'quvchi oqimi
def _make_round(p, room, round_no, start_pos, last_rq_id=None):
    """Yangi aylana: savollar yangi tasodifiy tartibda, variantlar ham qayta aralashtirilgan.

    Yangi aylana avvalgisining oxirgi savoli bilan boshlanmaydi (savol bittadan ko'p bo'lsa).
    """
    rqs = list(room.room_questions.order_by("order"))
    random.shuffle(rqs)
    if last_rq_id and len(rqs) > 1 and rqs[0].id == last_rq_id:
        j = random.randrange(1, len(rqs))
        rqs[0], rqs[j] = rqs[j], rqs[0]
    pqs = []
    for i, rq in enumerate(rqs):
        ids = [o["id"] for o in rq.snapshot["options"]]
        random.shuffle(ids)
        pqs.append(
            ParticipantQuestion(
                participant=p, room_question=rq, round=round_no, position=start_pos + i, option_order=ids
            )
        )
    ParticipantQuestion.objects.bulk_create(pqs)


def begin_participant(pid):
    """O'quvchi fullscreen'ga kirib 'Testni boshlash'ni bosganda."""
    with transaction.atomic():
        p = Participant.objects.select_for_update().select_related("room").get(pk=pid)
        room = refresh_room_clock(p.room)
        if p.status == P.ACTIVE:
            return p
        if p.status != P.WAITING:
            raise GameError("state", "Boshlab bo'lmaydi")
        if room.status == R.PAUSED:
            raise GameError("paused", "Test pauzada")
        if room.status != R.RUNNING:
            raise GameError("state", "Test hali boshlanmagan")
        _make_round(p, room, 1, 0)
        p.status = P.ACTIVE
        p.current_index = 0
        p.current_round = 1
        p.save(update_fields=["status", "current_index", "current_round"])
    ranking.update(p)
    events.teacher_update(room, throttle=True)
    return p


def _is_frozen(p, now=None):
    return bool(p.frozen_until and p.frozen_until > (now or timezone.now()))


def serve_question(pid):
    """Joriy savolni yuboradi va shown_at ni (server vaqti) belgilaydi."""
    with transaction.atomic():
        p = Participant.objects.select_for_update().select_related("room").get(pk=pid)
        room = refresh_room_clock(p.room)
        _check_can_play(p, room)
        pq = (
            ParticipantQuestion.objects.select_related("room_question")
            .filter(participant=p, position=p.current_index)
            .first()
        )
        if not pq:
            raise GameError("none", "Savol topilmadi")
        if pq.shown_at is None:
            pq.shown_at = timezone.now()
            pq.save(update_fields=["shown_at"])
        snap = pq.room_question.snapshot
        by_id = {o["id"]: o for o in snap["options"]}
        size = _total_questions(room)
        idx = pq.position - (pq.round - 1) * size
        return {
            "t": "question",
            "position": pq.position,
            "round": pq.round,
            "round_start": pq.round > 1 and idx == 0,
            "number": idx + 1,
            "total": size,
            "text": snap["text"],
            "code": snap.get("code", ""),
            "input_values": snap.get("input_values", ""),
            "image": snap.get("image"),
            "options": [{"id": i, "text": by_id[i]["text"]} for i in pq.option_order],
        }


def _check_can_play(p, room):
    now = timezone.now()
    if p.status != P.ACTIVE:
        raise GameError("state", "Siz hozir test yechmayapsiz")
    if room.status == R.PAUSED:
        raise GameError("paused", "Test pauzada")
    if room.status == R.FINISHED:
        dl = timer.participant_deadline(room, p)
        if not (p.extra_seconds and dl and now < dl):
            raise GameError("finished", "Vaqt tugadi")
    elif room.status != R.RUNNING:
        raise GameError("state", "Test ishlamayapti")
    if _has_pending_violation(p):
        raise GameError("locked", "Test qulflangan")
    if _is_frozen(p, now):
        raise GameError("frozen", "Ekraningiz muzlagan")


def _answer_payload(p, ans, new_code=None, duplicate=False):
    p.refresh_from_db()
    room = p.room
    codes = list(
        PowerUpCode.objects.filter(participant=p, is_used=False).values_list("code", flat=True)
    )
    return {
        "t": "answer_result",
        "uuid": str(ans.client_uuid),
        "position": ParticipantQuestion.objects.filter(
            participant=p, room_question_id=ans.room_question_id, round=ans.round
        ).values_list("position", flat=True).first(),
        "round": ans.round,
        "correct": ans.is_correct,
        "points": ans.points,
        "score": p.score,
        "streak": p.streak,
        "streak_target": STREAK_TARGET,
        "rank": ranking.rank_of(p),
        "top5": ranking.top(room, 5),
        "new_code": new_code,
        "codes": codes,
        "finished": p.status == P.FINISHED,
        "interval": room.interval_seconds,
        "duplicate": duplicate,
        "powerups": powerup_flags(room),
    }


def powerup_flags(room):
    on = room.powerups_enabled
    return {
        "steal": on and room.steal_enabled,
        "freeze": on and room.freeze_enabled,
        "steal_min": min(room.steal_min_percent, room.steal_max_percent),
        "steal_max": max(room.steal_min_percent, room.steal_max_percent),
        "freeze_min": min(room.freeze_min_seconds, room.freeze_max_seconds),
        "freeze_max": max(room.freeze_min_seconds, room.freeze_max_seconds),
    }


def _new_code():
    while True:
        c = secrets.token_hex(4).upper()
        if not PowerUpCode.objects.filter(code=c).exists():
            return c


def submit_answer(pid, position, option_id, client_uuid):
    """Javobni qabul qiladi. client_uuid bo'yicha idempotent."""
    new_code = None
    with transaction.atomic():
        p = Participant.objects.select_for_update().select_related("room").get(pk=pid)
        dup = Answer.objects.filter(client_uuid=client_uuid).first()
        if dup:
            if dup.participant_id != p.id:
                raise GameError("uuid", "Noto'g'ri so'rov")
            return _answer_payload(p, dup, duplicate=True)
        room = refresh_room_clock(p.room)
        _check_can_play(p, room)
        try:
            position = int(position)
            option_id = int(option_id)
        except (TypeError, ValueError):
            raise GameError("value", "Noto'g'ri so'rov")
        pq = (
            ParticipantQuestion.objects.select_related("room_question")
            .filter(participant=p, position=position)
            .first()
        )
        if not pq:
            raise GameError("none", "Savol topilmadi")
        prior = Answer.objects.filter(
            participant=p, room_question=pq.room_question, round=pq.round
        ).first()
        if prior:  # shu savolga allaqachon boshqa uuid bilan javob berilgan
            return _answer_payload(p, prior, duplicate=True)
        if position != p.current_index or pq.shown_at is None:
            raise GameError("order", "Bu savolga hozir javob berib bo'lmaydi")
        snap = pq.room_question.snapshot
        opt = next((o for o in snap["options"] if o["id"] == option_id), None)
        if opt is None:
            raise GameError("value", "Noto'g'ri variant")
        now = timezone.now()
        response_ms = max(0, int((now - pq.shown_at).total_seconds() * 1000))
        total_q = _total_questions(room)
        correct = bool(opt["is_correct"])
        points = calc_points(response_ms, question_scale_ms(room, total_q)) if correct else 0
        ans = Answer.objects.create(
            participant=p,
            room_question=pq.room_question,
            round=pq.round,
            selected_option_id=option_id,
            is_correct=correct,
            points=points,
            response_ms=response_ms,
            client_uuid=client_uuid,
        )
        p.score += points
        if correct:
            p.streak += 1
            if (
                room.powerups_enabled
                and (room.steal_enabled or room.freeze_enabled)
                and p.streak >= STREAK_TARGET
            ):
                unused = PowerUpCode.objects.filter(participant=p, is_used=False).count()
                if unused < MAX_UNUSED_CODES:
                    new_code = _new_code()
                    PowerUpCode.objects.create(participant=p, code=new_code)
                    p.streak = 0
                else:
                    p.streak = STREAK_TARGET
        else:
            p.streak = 0
        p.current_index = position + 1
        if not ParticipantQuestion.objects.filter(participant=p, position=p.current_index).exists():
            # aylana tugadi: vaqt bor ekan yangi aylana boshlanadi, vaqt tugagan bo'lsa yakun
            if room.status == R.RUNNING and room.ends_at and room.ends_at > now:
                p.current_round = pq.round + 1
                _make_round(p, room, p.current_round, p.current_index, last_rq_id=pq.room_question_id)
            else:
                p.status = P.FINISHED
                p.finished_at = now
        p.save(update_fields=["score", "streak", "current_index", "current_round", "status", "finished_at"])
    ranking.update(p)
    events.teacher_update(room, throttle=True)
    return _answer_payload(p, ans, new_code=new_code)


# ---------------------------------------------------------------- qoidabuzarlik
def report_violation(pid, vtype):
    if vtype not in Violation.Type.values:
        raise GameError("value", "Noto'g'ri turi")
    with transaction.atomic():
        p = Participant.objects.select_for_update().select_related("room", "school_class").get(pk=pid)
        room = p.room
        if p.status != P.ACTIVE or room.status != R.RUNNING:
            return None
        if _has_pending_violation(p):
            return None  # qulflangan, takror yozilmaydi
        v = Violation.objects.create(participant=p, type=vtype)
        ParticipantQuestion.objects.filter(participant=p, position=p.current_index).update(
            shown_at=None
        )
    events.refresh_participant(p.id)
    t = timezone.localtime(v.occurred_at).strftime("%H:%M:%S")
    label = {
        "fullscreen_exit": "oynadan chiqdi",
        "tab_switch": "boshqa oynaga o'tdi",
        "printscreen": "PrintScreen bosdi",
        "devtools": "DevTools ochishga urindi",
    }[vtype]
    events.teacher_update(
        room,
        alert={
            "kind": "violation",
            "id": v.id,
            "text": f"{p.first_name} {p.last_name} ({p.school_class.name}) {label} — {t}",
        },
    )
    return v


def decide_violation(room_id, violation_id, decision):
    if decision not in ("allowed", "kicked"):
        raise GameError("value", "Noto'g'ri qaror")
    with transaction.atomic():
        v = (
            Violation.objects.select_for_update()
            .select_related("participant__room")
            .filter(pk=violation_id, participant__room_id=room_id)
            .first()
        )
        if not v or v.decision != Violation.Decision.PENDING:
            raise GameError("none", "Qoidabuzarlik topilmadi yoki hal qilingan")
        v.decision = decision
        v.decided_at = timezone.now()
        v.save(update_fields=["decision", "decided_at"])
        p = v.participant
        if decision == "kicked":
            p.status = P.KICKED
            p.save(update_fields=["status"])
    ranking.update(p)
    events.refresh_participant(p.id)
    events.teacher_update(p.room)


# ---------------------------------------------------------------- holat (state)
def participant_result(p, room):
    # foiz = to'g'ri javoblar / jami javoblar (barcha aylanalar bo'yicha)
    total_a = Answer.objects.filter(participant=p).count()
    correct = Answer.objects.filter(participant=p, is_correct=True).count()
    percent = round(correct * 100 / total_a, 1) if total_a else 0
    rounds = Answer.objects.filter(participant=p).order_by("-round").values_list("round", flat=True).first() or 0
    return {
        "correct": correct,
        "total": total_a,
        "rounds": rounds,
        "percent": percent,
        "grade": room.grade_for_percent(percent),
        "score": p.score,
        "rank": ranking.rank_of(p),
        "codes": PowerUpCode.objects.filter(participant=p).count(),
    }


def review_payload(p):
    answers = {(a.room_question_id, a.round): a for a in Answer.objects.filter(participant=p)}
    items = []
    for pq in ParticipantQuestion.objects.filter(participant=p).select_related("room_question"):
        ans = answers.get((pq.room_question_id, pq.round))
        if ans is None:
            continue  # hali ko'rsatilmagan/javobsiz aylana savollari ko'rib chiqishga kirmaydi
        snap = pq.room_question.snapshot
        sel = ans.selected_option_id if ans else None
        by_id = {o["id"]: o for o in snap["options"]}
        items.append(
            {
                "number": pq.position + 1,
                "round": pq.round,
                "topic": snap.get("topic", ""),
                "is_correct": bool(ans and ans.is_correct),
                "text": snap["text"],
                "code": snap.get("code", ""),
                "image": snap.get("image"),
                "answered": ans is not None,
                "options": [
                    {
                        "text": by_id[i]["text"],
                        "correct": by_id[i]["is_correct"],
                        "selected": i == sel,
                    }
                    for i in pq.option_order
                ],
            }
        )
    return items


def time_sync(pid):
    """Yengil vaqt sinxronlash xabari (mijoz soatiga ishonilmaydi)."""
    p = Participant.objects.select_related("room").get(pk=pid)
    room = refresh_room_clock(p.room)
    now = timezone.now()
    return {
        "t": "pong",
        "server_now": now.timestamp(),
        "status": room.status,
        "remaining": timer.participant_remaining(room, p, now),
    }


def student_state(pid):
    p = Participant.objects.select_related("room", "school_class").get(pk=pid)
    room = refresh_room_clock(p.room)
    now = timezone.now()
    # vaqti tugagan o'quvchini yakunlash
    if room.status == R.FINISHED and p.status in (P.WAITING, P.ACTIVE):
        dl = timer.participant_deadline(room, p)
        if not (p.status == P.ACTIVE and p.extra_seconds and dl and now < dl):
            _finish_participant(p, now)
    frozen_left = max(0.0, (p.frozen_until - now).total_seconds()) if _is_frozen(p, now) else 0.0
    state = {
        "t": "state",
        "server_now": now.timestamp(),
        "room": {
            "name": room.name,
            "status": room.status,
            "remaining": timer.participant_remaining(room, p, now),
            "interval": room.interval_seconds,
        },
        "me": {
            "id": p.id,
            "name": f"{p.first_name} {p.last_name}",
            "school_class": p.school_class.name,
            "avatar": p.avatar,
            "score": p.score,
            "streak": p.streak,
            "streak_target": STREAK_TARGET,
        },
        "frozen_left": frozen_left,
        "powerups": powerup_flags(room),
    }
    if p.status == P.PENDING:
        phase = "pending"
    elif p.status == P.KICKED:
        # kech kirish so'rovi rad etilgan (hech qachon savol ko'rmagan)
        rejected = p.is_late and not p.question_order.exists()
        phase = "rejected" if rejected else "kicked"
    elif p.status == P.FINISHED:
        phase = "finished"
        state["result"] = participant_result(p, room)
        state["room_finished"] = room.status == R.FINISHED
        if room.status == R.FINISHED:
            state["podium"] = ranking.top(room, 3)
        if room.status == R.FINISHED and room.results_visible:
            state["review"] = review_payload(p)
            weak = {}
            for it in state["review"]:
                w = weak.setdefault(it["topic"], [0, 0])
                w[1] += 1
                w[0] += 0 if it["is_correct"] else 1
            state["weak_topics"] = sorted(
                ({"topic": t, "wrong": v[0], "total": v[1]} for t, v in weak.items() if v[0]),
                key=lambda x: -x["wrong"] / x["total"],
            )
    elif room.status == R.WAITING:
        phase = "lobby"
    elif p.status == P.WAITING:
        phase = "paused" if room.status == R.PAUSED else "ready"
    else:  # ACTIVE
        if _has_pending_violation(p):
            phase = "locked"
        elif room.status == R.PAUSED:
            phase = "paused"
        elif frozen_left > 0:
            phase = "frozen"
        else:
            phase = "question"
            size = _total_questions(room)
            state["round"] = p.current_round
            state["answered"] = p.current_index - (p.current_round - 1) * size
            state["total"] = size
    state["phase"] = phase
    if phase == "lobby":
        state["players"] = [
            {"id": x.id, "name": x.first_name, "avatar": x.avatar}
            for x in room.participants.filter(status=P.WAITING).order_by("-joined_at")[:60]
        ]
    if phase in ("question", "ready", "paused", "frozen", "locked"):
        state["codes"] = list(
            PowerUpCode.objects.filter(participant=p, is_used=False).values_list("code", flat=True)
        )
    return state
