import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from questions.models import SchoolClass
from quiz import powerups, services, timer
from quiz.models import Answer, Participant, ParticipantQuestion, PowerUpCode, PowerUpLog, Violation
from quiz.services import GameError
from rooms.models import Room
from rooms.services import create_room_with_questions

pytestmark = pytest.mark.django_db


def make_questions(teacher, n=5):
    from questions.models import Question, QuestionOption, Subject, Topic

    subject, _ = Subject.objects.get_or_create(teacher=teacher, name="Python")
    topic, _ = Topic.objects.get_or_create(teacher=teacher, subject=subject, name="Sikllar", defaults={"order": 1})
    qs = []
    for i in range(n):
        q = Question.objects.create(teacher=teacher, topic=topic, text=f"Savol {i}")
        for j in range(4):
            QuestionOption.objects.create(question=q, text=f"V{j}", is_correct=(j == 0))
        qs.append(q)
    return qs


@pytest.fixture
def setup():
    teacher = User.objects.create_user("t", password="x")
    cls = SchoolClass.objects.create(name="7-A")
    qs = make_questions(teacher, 6)
    room = create_room_with_questions(
        teacher,
        dict(name="Test", password="1234", duration_minutes=10, interval_seconds=3),
        qs,
    )
    return teacher, cls, room


def join(room, cls, name="Ali", wait=True):
    return services.join_room(room.code, "1234", name, "Valiyev", cls.id, "a01")


def start_and_begin(room, *participants):
    services.start_room(room.id)
    for p in participants:
        services.begin_participant(p.id)


def correct_option(p, position):
    pq = ParticipantQuestion.objects.select_related("room_question").get(
        participant=p, position=position
    )
    return next(o["id"] for o in pq.room_question.snapshot["options"] if o["is_correct"])


def wrong_option(p, position):
    pq = ParticipantQuestion.objects.select_related("room_question").get(
        participant=p, position=position
    )
    return next(o["id"] for o in pq.room_question.snapshot["options"] if not o["is_correct"])


def answer(p, position, correct=True):
    services.serve_question(p.id)
    opt = correct_option(p, position) if correct else wrong_option(p, position)
    return services.submit_answer(p.id, position, opt, uuid.uuid4())


# ---- ball
def test_points_formula():
    assert services.calc_points(0, 20000) == 1000
    assert services.calc_points(20000, 20000) == 500
    assert services.calc_points(999999, 20000) == 500
    assert 500 < services.calc_points(10000, 20000) < 1000


def test_correct_gives_points_wrong_zero(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    r = answer(p, 0, True)
    assert r["correct"] and 500 <= r["points"] <= 1000
    r2 = answer(p, 1, False)
    assert not r2["correct"] and r2["points"] == 0
    p.refresh_from_db()
    assert p.score == r["points"]


def test_snapshot_survives_question_edit(setup):
    teacher, cls, room = setup
    from questions.models import Question

    Question.objects.all().update(text="O'zgartirildi")
    rq = room.room_questions.first()
    assert rq.snapshot["text"].startswith("Savol")


def test_shuffle_is_stable_and_hidden_answers(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    q1 = services.serve_question(p.id)
    q2 = services.serve_question(p.id)
    assert q1 == q2
    assert all("is_correct" not in o for o in q1["options"])


# ---- takroriy javob
def test_duplicate_uuid_counts_once(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    services.serve_question(p.id)
    u = uuid.uuid4()
    opt = correct_option(p, 0)
    r1 = services.submit_answer(p.id, 0, opt, u)
    r2 = services.submit_answer(p.id, 0, opt, u)
    assert r2["duplicate"] and r1["score"] == r2["score"]
    assert Answer.objects.filter(participant=p).count() == 1


def test_cannot_answer_old_or_future_question(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    answer(p, 0)
    with pytest.raises(GameError):
        services.submit_answer(p.id, 3, correct_option(p, 3), uuid.uuid4())


# ---- streak va kod
def test_streak_awards_code_and_resets(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    answer(p, 0)
    answer(p, 1)
    r = answer(p, 2)
    assert r["new_code"]
    p.refresh_from_db()
    assert p.streak == 0
    assert PowerUpCode.objects.filter(participant=p, is_used=False).count() == 1


def test_wrong_answer_resets_streak(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    answer(p, 0)
    answer(p, 1)
    answer(p, 2, correct=False)
    p.refresh_from_db()
    assert p.streak == 0
    assert not PowerUpCode.objects.exists()


# ---- super-kuchlar
def two_players(setup):
    _, cls, room = setup
    a, b = join(room, cls, "Ali"), join(room, cls, "Vali")
    start_and_begin(room, a, b)
    return room, a, b


def give_code(p):
    return PowerUpCode.objects.create(participant=p, code=f"C{PowerUpCode.objects.count()}X").code


def test_steal_random_amount_within_range_and_conserves_points(setup):
    room, a, b = two_players(setup)
    Room.objects.filter(pk=room.pk).update(steal_min_percent=5, steal_max_percent=20)
    seen = set()
    for _ in range(25):
        Participant.objects.filter(pk=b.pk).update(score=1000, frozen_until=None)
        Participant.objects.filter(pk=a.pk).update(score=0, last_target=None)
        res = powerups.use_powerup(a.id, give_code(a), "steal")
        a.refresh_from_db(); b.refresh_from_db()
        assert 50 <= res["amount"] <= 200  # 1000 ning 5–20 %
        assert a.score == res["amount"] and b.score == 1000 - res["amount"] and a.score + b.score == 1000
        assert res["target"]["id"] == b.id and res["range"] == [5, 20]
        seen.add(res["amount"])
    assert len(seen) > 3  # miqdor haqiqatan tasodifiy


def test_steal_never_negative_and_zero_score_not_a_target(setup):
    room, a, b = two_players(setup)
    Participant.objects.filter(pk=b.pk).update(score=0)
    code = give_code(a)
    with pytest.raises(GameError) as e:
        powerups.use_powerup(a.id, code, "steal")
    assert e.value.code == "no_target"
    assert PowerUpCode.objects.get(code=code).is_used is False  # kod yo'qolmadi
    Participant.objects.filter(pk=b.pk).update(score=3)
    res = powerups.use_powerup(a.id, code, "steal")
    b.refresh_from_db()
    assert res["amount"] == 1 and b.score == 2  # kichik ball: kamida 1, manfiy emas


def test_freeze_random_seconds_within_range(setup):
    room, a, b = two_players(setup)
    Room.objects.filter(pk=room.pk).update(freeze_min_seconds=5, freeze_max_seconds=15)
    seen = set()
    for _ in range(25):
        Participant.objects.filter(pk=b.pk).update(frozen_until=None)
        Participant.objects.filter(pk=a.pk).update(last_target=None)
        res = powerups.use_powerup(a.id, give_code(a), "freeze")
        b.refresh_from_db()
        assert 5 <= res["seconds"] <= 15
        left = (b.frozen_until - timezone.now()).total_seconds()
        assert res["seconds"] - 2 < left <= res["seconds"]
        seen.add(res["seconds"])
    assert len(seen) > 3
    log = PowerUpLog.objects.filter(type="freeze").order_by("id").last()
    assert log.freeze_seconds == res["seconds"] and log.points_amount == 0


def test_target_is_random_among_eligible_only(setup):
    _, cls, room = setup
    a = join(room, cls, "A")
    others = [join(room, cls, n) for n in ("B", "C", "D", "E")]
    kicked = join(room, cls, "K")
    waiting = join(room, cls, "W")  # test boshlanmaydi -> kutayotgan
    start_and_begin(room, a, *others, kicked)
    services.kick_participant(room.id, kicked.id)
    Participant.objects.filter(pk=others[0].pk).update(status="finished")
    Participant.objects.filter(pk=others[1].pk).update(frozen_until=timezone.now() + timedelta(seconds=60))
    Participant.objects.filter(pk__in=[o.pk for o in others]).update(score=500)
    ok_ids = {others[2].id, others[3].id}
    hit = set()
    for _ in range(30):
        Participant.objects.filter(pk=a.pk).update(last_target=None)
        res = powerups.use_powerup(a.id, give_code(a), "steal")
        assert res["target"]["id"] in ok_ids  # o'zi, chetlatilgan, kutayotgan, tugatgan, muzlagan tushmaydi
        hit.add(res["target"]["id"])
        Participant.objects.filter(pk__in=ok_ids).update(score=500)
    assert hit == ok_ids  # ikkalasi ham ba'zan tanlanadi (tasodifiy)
    assert res["reel"] and res["target"]["id"] in [r["id"] for r in res["reel"]]
    assert all(r["id"] in ok_ids for r in res["reel"])  # baraban faqat mos o'quvchilarni ko'rsatadi


def test_never_same_target_twice_in_a_row(setup):
    _, cls, room = setup
    a, b, c = join(room, cls, "A"), join(room, cls, "B"), join(room, cls, "C")
    start_and_begin(room, a, b, c)
    Participant.objects.filter(pk__in=[b.pk, c.pk]).update(score=1000)
    last = None
    for _ in range(20):
        res = powerups.use_powerup(a.id, give_code(a), "steal")
        assert res["target"]["id"] != last
        last = res["target"]["id"]


def test_no_eligible_target_keeps_code_and_reports(setup):
    _, cls, room = setup
    a = join(room, cls, "A")
    start_and_begin(room, a)
    code = give_code(a)
    with pytest.raises(GameError) as e:
        powerups.use_powerup(a.id, code, "freeze")
    assert e.value.code == "no_target" and "saqlanib" in e.value.message
    assert PowerUpCode.objects.get(code=code).is_used is False
    assert not PowerUpLog.objects.exists()


def test_code_single_use_and_owner_only(setup):
    room, a, b = two_players(setup)
    Participant.objects.filter(pk__in=[a.pk, b.pk]).update(score=500)
    code = give_code(a)
    with pytest.raises(GameError):
        powerups.use_powerup(b.id, code, "freeze")  # egasi emas
    powerups.use_powerup(a.id, code, "freeze")
    Participant.objects.filter(pk=b.pk).update(frozen_until=None)
    Participant.objects.filter(pk=a.pk).update(last_target=None)
    with pytest.raises(GameError):
        powerups.use_powerup(a.id, code, "freeze")  # ikkinchi marta


def test_client_cannot_choose_target(setup):
    import inspect

    assert list(inspect.signature(powerups.use_powerup).parameters) == ["attacker_id", "code", "kind"]


def test_frozen_cannot_answer_and_cannot_use_powerup(setup):
    room, a, b = two_players(setup)
    powerups.use_powerup(a.id, give_code(a), "freeze")
    with pytest.raises(GameError) as e:
        services.serve_question(b.id)
    assert e.value.code == "frozen"
    assert services.student_state(b.id)["phase"] == "frozen"
    with pytest.raises(GameError) as e2:
        powerups.use_powerup(b.id, give_code(b), "steal")
    assert e2.value.code == "frozen"


def test_victim_notice_text(setup, monkeypatch):
    from quiz import events

    room, a, b = two_players(setup)
    seen = []
    monkeypatch.setattr(events, "notice", lambda pid, **kw: seen.append((pid, kw)))
    Participant.objects.filter(pk=b.pk).update(score=1000)
    res = powerups.use_powerup(a.id, give_code(a), "steal")
    pid, kw = seen[-1]
    assert pid == b.id and kw["text"] == f"💰 Ali sendan {res['amount']} ball oldi!"
    Participant.objects.filter(pk=a.pk).update(last_target=None)
    res = powerups.use_powerup(a.id, give_code(a), "freeze")
    pid, kw = seen[-1]
    assert kw["text"] == f"❄️ Ali seni {res['seconds']} soniyaga muzlatdi!"


def test_disabled_powerup_rejected(setup):
    room, a, b = two_players(setup)
    Room.objects.filter(pk=room.pk).update(freeze_enabled=False)
    with pytest.raises(GameError):
        powerups.use_powerup(a.id, give_code(a), "freeze")


# ---- qoidabuzarlik
def test_violation_locks_until_teacher_decides(setup):
    room, a, b = two_players(setup)
    v = services.report_violation(a.id, "tab_switch")
    assert v and services.student_state(a.id)["phase"] == "locked"
    with pytest.raises(GameError):
        services.serve_question(a.id)
    services.decide_violation(room.id, v.id, "allowed")
    assert services.student_state(a.id)["phase"] == "question"
    v2 = services.report_violation(a.id, "fullscreen_exit")
    services.decide_violation(room.id, v2.id, "kicked")
    assert services.student_state(a.id)["phase"] == "kicked"
    assert Violation.objects.filter(participant=a).count() == 2


# ---- taymer
def test_timer_pause_resume_add_time(setup):
    _, cls, room = setup
    join(room, cls)
    services.start_room(room.id)
    room.refresh_from_db()
    assert 595 < timer.room_remaining(room) <= 600
    services.pause_room(room.id)
    room.refresh_from_db()
    t0 = timezone.now()
    # pauzada taymer to'xtaydi: istalgan paytda bir xil qiymat
    assert timer.room_remaining(room, t0) == timer.room_remaining(room, t0 + timedelta(minutes=5))
    # 30 soniyalik pauzani simulyatsiya qilamiz
    ends_before = room.ends_at
    Room.objects.filter(pk=room.pk).update(paused_at=timezone.now() - timedelta(seconds=30))
    services.resume_room(room.id)
    room.refresh_from_db()
    assert room.ends_at >= ends_before + timedelta(seconds=29)
    assert room.total_paused_seconds >= 29
    services.add_time(room.id, 300)
    room.refresh_from_db()
    assert timer.room_remaining(room) > 890


def test_auto_finish_when_time_over(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    Room.objects.filter(pk=room.pk).update(ends_at=timezone.now() - timedelta(seconds=1))
    state = services.student_state(p.id)
    assert state["phase"] == "finished"
    room.refresh_from_db()
    assert room.status == Room.Status.FINISHED


def test_late_join_requires_approval(setup):
    _, cls, room = setup
    a = join(room, cls)
    start_and_begin(room, a)
    late = join(room, cls, "Kech")
    assert late.status == "pending" and late.is_late
    services.decide_late(room.id, late.id, True, 60)
    late.refresh_from_db()
    assert late.status == "waiting" and late.extra_seconds == 60
    services.begin_participant(late.id)
    assert services.student_state(late.id)["phase"] == "question"


def test_wrong_password_rejected(setup):
    _, cls, room = setup
    with pytest.raises(GameError):
        services.join_room(room.code, "xato", "A", "B", cls.id, "a01")


def test_grades(setup):
    _, _, room = setup
    assert [room.grade_for_percent(x) for x in (100, 86, 85, 71, 70, 56, 55)] == [5, 5, 4, 4, 3, 3, 2]


def test_finish_whole_flow(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    for i in range(6):
        r = answer(p, i)
    # savollar tugadi, lekin vaqt bor: yangi aylana boshlanadi (test vaqt bilan cheklanadi)
    assert not r["finished"]
    st = services.student_state(p.id)
    assert st["phase"] == "question" and st["round"] == 2 and st["answered"] == 0
    services.finish_room(room.id)
    st = services.student_state(p.id)
    assert st["phase"] == "finished" and st["result"]["correct"] == 6 and st["result"]["total"] == 6
    assert "review" not in st
    services.set_results_visible(room.id, True)
    st = services.student_state(p.id)
    p.refresh_from_db()
    assert st["review"] and len(st["review"]) == 6  # faqat javob berilganlar
    assert st["podium"][0]["score"] == p.score and st["podium"][0]["rank"] == 1


# ---------------------------------------------------------------- 7-bosqich: aylanalar
def play_round(p, size, start, correct=True):
    out = None
    for pos in range(start, start + size):
        out = answer(p, pos, correct)
    return out


def test_new_round_reshuffles_and_never_starts_with_last_question(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    r1 = ParticipantQuestion.objects.filter(participant=p, round=1).order_by("position")
    assert r1.count() == 6 and [x.position for x in r1] == list(range(6))
    last_rq = r1.last().room_question_id
    play_round(p, 6, 0)
    p.refresh_from_db()
    assert p.current_round == 2 and p.current_index == 6
    r2 = ParticipantQuestion.objects.filter(participant=p, round=2).order_by("position")
    assert [x.position for x in r2] == list(range(6, 12))
    assert sorted(x.room_question_id for x in r2) == sorted(x.room_question_id for x in r1)  # bir xil savollar
    assert r2.first().room_question_id != last_rq  # oldingi aylananing oxirgisi bilan boshlanmaydi


def test_first_question_rule_holds_over_many_rounds(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    for rnd in range(1, 6):
        last = ParticipantQuestion.objects.filter(participant=p, round=rnd).order_by("position").last()
        play_round(p, 6, (rnd - 1) * 6)
        first = ParticipantQuestion.objects.filter(participant=p, round=rnd + 1).order_by("position").first()
        assert first.room_question_id != last.room_question_id


def test_options_reshuffled_between_rounds(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    play_round(p, 6, 0)
    changed = 0
    for rq_id in set(ParticipantQuestion.objects.filter(participant=p).values_list("room_question_id", flat=True)):
        a = ParticipantQuestion.objects.get(participant=p, round=1, room_question_id=rq_id).option_order
        b = ParticipantQuestion.objects.get(participant=p, round=2, room_question_id=rq_id).option_order
        assert sorted(a) == sorted(b)
        changed += a != b
    assert changed >= 1  # 6 ta savoldan kamida bittasida variantlar tartibi o'zgargan (4! = 24 ehtimol)


def test_repeat_question_scores_and_each_attempt_stored(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    play_round(p, 6, 0)
    r = answer(p, 6)  # 2-aylananing birinchi savoli
    assert r["correct"] and r["points"] >= 500 and r["round"] == 2
    p.refresh_from_db()
    from quiz.models import Answer

    assert Answer.objects.filter(participant=p, round=1).count() == 6
    assert Answer.objects.filter(participant=p, round=2).count() == 1
    rq = ParticipantQuestion.objects.get(participant=p, position=6).room_question
    assert Answer.objects.filter(participant=p, room_question=rq).count() == 2  # bitta savol, ikki urinish


def test_question_payload_has_round_info_and_banner_flag(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    q1 = services.serve_question(p.id)
    assert q1["round"] == 1 and q1["round_start"] is False and q1["total"] == 6 and q1["number"] == 1
    play_round(p, 6, 0)
    q2 = services.serve_question(p.id)
    assert q2["round"] == 2 and q2["round_start"] is True and q2["number"] == 1 and q2["position"] == 6
    assert "is_correct" not in str(q2)


def test_duplicate_uuid_in_second_round_idempotent(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    play_round(p, 6, 0)
    services.serve_question(p.id)
    opt = correct_option(p, 6)
    u = uuid.uuid4()
    r1 = services.submit_answer(p.id, 6, opt, u)
    r2 = services.submit_answer(p.id, 6, opt, u)
    assert r2["duplicate"] and r2["score"] == r1["score"]


def test_percent_counts_all_answers_across_rounds(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    play_round(p, 6, 0, correct=True)
    play_round(p, 3, 6, correct=False)
    services.finish_room(room.id)
    res = services.student_state(p.id)["result"]
    assert res["total"] == 9 and res["correct"] == 6 and res["percent"] == 66.7 and res["rounds"] == 2
    assert res["grade"] == 3


def test_time_over_ends_participant_instead_of_new_round(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    for i in range(5):
        answer(p, i)
    services.serve_question(p.id)
    Room.objects.filter(pk=room.pk).update(ends_at=timezone.now() + timedelta(seconds=1))
    opt = correct_option(p, 5)
    services.submit_answer(p.id, 5, opt, uuid.uuid4())  # hali vaqt bor -> yangi aylana
    p.refresh_from_db()
    assert p.current_round == 2
    Room.objects.filter(pk=room.pk).update(ends_at=timezone.now() - timedelta(seconds=1))
    assert services.student_state(p.id)["phase"] == "finished"


def test_teacher_snapshot_shows_round(setup):
    from quiz import snapshots

    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    play_round(p, 6, 0)
    answer(p, 6)
    row = snapshots.teacher_snapshot(room)["participants"][0]
    assert row["round"] == 2 and row["answered"] == 7 and row["in_round"] == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_steals_keep_points_consistent(setup):
    """Bir vaqtda ikki hujum: jami ball saqlanishi va manfiy bo'lmasligi kerak."""
    import threading

    from django.db import connection

    _, cls, room = setup
    a, b, v = join(room, cls, "A"), join(room, cls, "B"), join(room, cls, "V")
    start_and_begin(room, a, b, v)
    Participant.objects.filter(pk__in=[a.pk, b.pk, v.pk]).update(score=0)
    Participant.objects.filter(pk=v.pk).update(score=1000)
    ca, cb = give_code(a), give_code(b)
    errors = []

    def attack(att, code):
        try:
            powerups.use_powerup(att.id, code, "steal")
        except GameError as e:
            errors.append(e)
        finally:
            connection.close()

    ts = [threading.Thread(target=attack, args=(a, ca)), threading.Thread(target=attack, args=(b, cb))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    for p in (a, b, v):
        p.refresh_from_db()
    # nishon tasodifiy: a yoki b ham nishon bo'lishi mumkin; muhimi — jami ball saqlanadi, manfiy yo'q
    assert all(e.code == "no_target" for e in errors)
    assert a.score + b.score + v.score == 1000
    assert min(a.score, b.score, v.score) >= 0
    assert PowerUpLog.objects.count() == 2 - len(errors)


# ---------------------------------------------------------------- 5-bosqich: kirish, kutish xonasi, kech kirish
def test_lobby_shows_players_and_teacher_can_kick(setup):
    _, cls, room = setup
    a, b = join(room, cls, "Ali"), join(room, cls, "Vali")
    st = services.student_state(a.id)
    assert st["phase"] == "lobby" and {x["name"] for x in st["players"]} == {"Ali", "Vali"}
    assert all(x["avatar"] for x in st["players"])
    services.kick_participant(room.id, b.id)
    assert services.student_state(b.id)["phase"] == "kicked"
    assert {x["name"] for x in services.student_state(a.id)["players"]} == {"Ali"}  # chiqarilgan ro'yxatdan ketadi


def test_late_reject_gives_rejected_phase_and_cannot_play(setup):
    _, cls, room = setup
    join(room, cls, "Ali")
    services.start_room(room.id)
    late = join(room, cls, "Kech")
    assert services.student_state(late.id)["phase"] == "pending"
    with pytest.raises(services.GameError):
        services.begin_participant(late.id)  # ruxsatsiz boshlab bo'lmaydi
    services.decide_late(room.id, late.id, False)
    assert services.student_state(late.id)["phase"] == "rejected"
    with pytest.raises(services.GameError):
        services.decide_late(room.id, late.id, True)  # qaror ikki marta qabul qilinmaydi


def test_late_allowed_shares_global_timer_and_marked_late(setup):
    _, cls, room = setup
    join(room, cls, "Ali")
    services.start_room(room.id)
    late = join(room, cls, "Kech")
    services.decide_late(room.id, late.id, True, 0)
    st = services.student_state(late.id)
    assert st["phase"] == "ready"
    assert 0 < st["room"]["remaining"] <= room.duration_minutes * 60
    late.refresh_from_db()
    assert late.is_late


def test_late_alert_carries_pid_and_time(setup, monkeypatch):
    from quiz import events

    _, cls, room = setup
    join(room, cls, "Ali")
    services.start_room(room.id)
    seen = {}
    monkeypatch.setattr(events, "teacher_update", lambda r, alert=None: seen.update(alert=alert))
    p = join(room, cls, "Kech")
    a = seen["alert"]
    assert a["kind"] == "late" and a["pid"] == p.id and "Kech Valiyev (7-A)" in a["text"] and ":" in a["text"]


# ---------------------------------------------------------------- 6-bosqich: real vaqt, taymer, Celery
def test_time_sync_message_uses_server_time(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    m = services.time_sync(p.id)
    assert m["t"] == "pong" and m["status"] == "running" and 595 < m["remaining"] <= 600
    services.pause_room(room.id)
    a = services.time_sync(p.id)["remaining"]
    b = services.time_sync(p.id)["remaining"]
    assert a == b and services.time_sync(p.id)["status"] == "paused"
    services.add_time(room.id, 120)
    assert services.time_sync(p.id)["remaining"] > a + 100  # qo'shilgan vaqt darhol ko'rinadi


def test_pause_does_not_burn_freeze_time(setup):
    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    Participant.objects.filter(pk=p.pk).update(frozen_until=timezone.now() + timedelta(seconds=20))
    services.pause_room(room.id)
    Room.objects.filter(pk=room.pk).update(paused_at=timezone.now() - timedelta(seconds=30))
    services.resume_room(room.id)
    p.refresh_from_db()
    assert (p.frozen_until - timezone.now()).total_seconds() > 40  # 20 s + 30 s pauza


def test_celery_finish_task_logic(setup):
    from quiz.tasks import finish_room_task

    _, cls, room = setup
    p = join(room, cls)
    start_and_begin(room, p)
    # vaqt tugamagan: tugatmaydi (rejalashtiradi)
    assert finish_room_task(room.id) == "rescheduled"
    room.refresh_from_db()
    assert room.status == Room.Status.RUNNING
    # pauzada: o'tkazib yuboradi
    services.pause_room(room.id)
    assert finish_room_task(room.id) == "skip"
    services.resume_room(room.id)
    # vaqt tugadi: hamma topshiriladi
    Room.objects.filter(pk=room.pk).update(ends_at=timezone.now() - timedelta(seconds=2))
    assert finish_room_task(room.id) == "finished"
    room.refresh_from_db()
    p.refresh_from_db()
    assert room.status == Room.Status.FINISHED and p.status == "finished"
    assert finish_room_task(room.id) == "skip"  # takror chaqirish zarar qilmaydi


def test_projector_snapshot_hides_teacher_only_data(setup):
    from quiz import snapshots

    _, cls, room = setup
    a = join(room, cls)
    start_and_begin(room, a)
    services.report_violation(a.id, "tab_switch")
    full = snapshots.teacher_snapshot(room)
    proj = snapshots.projector_snapshot(room)
    assert full["violations"] and proj["violations"] == [] and proj["late"] == []
    assert proj["participants"][0]["violations"] == 0 and not proj["participants"][0]["locked"]
    assert proj["room"]["code"] == room.code and proj["room"]["results_visible"] is False
