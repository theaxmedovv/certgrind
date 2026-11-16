"""9-bosqich: natijalar, Excel eksport, statistika, xatolarni ko'rish."""
import uuid
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from openpyxl import load_workbook

from questions import sets as qsets
from questions.models import Question, QuestionOption, SchoolClass, Subject, Topic
from quiz import powerups, services
from quiz.models import Answer, Participant, ParticipantQuestion, PowerUpCode, PowerUpLog
from rooms.models import Room
from rooms.services import create_room_from_set
from stats import services as stats

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    t = User.objects.create_user("t", password="x")
    cls = SchoolClass.objects.create(name="7-A")
    subj = Subject.objects.create(teacher=t, name="Python")
    topics = []
    questions = []
    for i, name in enumerate(["O'zgaruvchilar", "Sikllar", "Funksiyalar"], 1):
        tp = Topic.objects.create(teacher=t, subject=subj, name=name, order=i)
        topics.append(tp)
        for j in range(2):
            q = Question.objects.create(teacher=t, topic=tp, text=f"{name} {j}", code="x = 1", difficulty="easy")
            QuestionOption.objects.create(question=q, text="to'g'ri", is_correct=True)
            QuestionOption.objects.create(question=q, text="xato")
            questions.append(q)
    qset = qsets.save_set(t, subj, "1–3-mavzular", "cumulative", topics, 6, "equal", None, questions)
    room = create_room_from_set(t, dict(name="R", password="1", duration_minutes=10, interval_seconds=1), qset)
    return t, cls, room, qset


def join(room, cls, name):
    return services.join_room(room.code, "1", name, "Valiyev", cls.id, "a01")


def play(p, position, correct=True):
    services.serve_question(p.id)
    pq = ParticipantQuestion.objects.select_related("room_question").get(participant=p, position=position)
    opts = pq.room_question.snapshot["options"]
    opt = next(o for o in opts if o["is_correct"] == correct)
    return services.submit_answer(p.id, position, opt["id"], uuid.uuid4())


def topic_of(p, position):
    return ParticipantQuestion.objects.select_related("room_question").get(participant=p, position=position).room_question.snapshot["topic"]


def test_results_rows_percent_over_all_rounds_and_extra_columns(world):
    t, cls, room, _ = world
    a, b = join(room, cls, "Ali"), join(room, cls, "Vali")
    services.start_room(room.id)
    services.begin_participant(a.id); services.begin_participant(b.id)
    for i in range(6):
        play(a, i)          # 1-aylana: hammasi to'g'ri
    for i in range(6, 9):
        play(a, i, correct=False)  # 2-aylana: 3 ta xato
    Participant.objects.filter(pk=b.pk).update(score=1000)
    Participant.objects.filter(pk=a.pk).update(score=0)
    PowerUpCode.objects.create(participant=a, code="ZZ11")
    powerups.use_powerup(a.id, "ZZ11", "steal")
    PowerUpCode.objects.create(participant=b, code="ZZ22")
    Participant.objects.filter(pk=a.pk).update(score=500)
    b.refresh_from_db()
    PowerUpLog.objects.create(room=room, attacker=a, victim=b, type="freeze", freeze_seconds=9)
    services.finish_room(room.id)
    rows = {r["first_name"]: r for r in stats.results_rows(room)}
    ra = rows["Ali"]
    assert ra["answered"] == 9 and ra["correct"] == 6 and ra["percent"] == 66.7 and ra["grade"] == 3
    assert ra["rounds"] == 2 and ra["stolen"] > 0
    assert rows["Vali"]["lost"] == ra["stolen"] and rows["Vali"]["frozen_seconds"] == 9
    assert rows["Vali"]["answered"] == 0 and rows["Vali"]["percent"] == 0


def test_excel_export_has_all_spec_columns(client, world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    play(a, 0)
    services.finish_room(room.id)
    client.login(username="t", password="x")
    r = client.get(reverse("results_export", args=[room.pk]))
    ws = load_workbook(BytesIO(r.content)).active
    header = [c.value for c in ws[1]]
    for need in ("Ism", "Familiya", "Sinf", "Jami javoblar", "To'g'ri javoblar", "Foiz (%)", "Ball", "Baho", "O'rin",
                 "Aylanalar soni", "Qoidabuzarliklar soni", "Sarflangan vaqt", "Kech kirgan", "Olingan maxfiy kodlar",
                 "O'g'irlangan ball", "Yo'qotilgan ball", "Muzlatilgan soniyalar"):
        assert need in header, need
    row = dict(zip(header, [c.value for c in ws[2]]))
    assert row["Ism"] == "Ali" and row["Jami javoblar"] == 1 and row["To'g'ri javoblar"] == 1 and row["Foiz (%)"] == 100


def test_results_hidden_until_teacher_allows_review(world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    play(a, 0)
    services.finish_room(room.id)
    st = services.student_state(a.id)
    assert st["phase"] == "finished" and "review" not in st and "weak_topics" not in st
    assert {"score", "grade", "rank"} <= set(st["result"])  # faqat ball, baho, o'rin
    services.set_results_visible(room.id, True)
    st = services.student_state(a.id)
    assert st["review"] and st["review"][0]["code"] == "x = 1"
    item = st["review"][0]
    assert any(o["correct"] for o in item["options"]) and item["is_correct"] is True


def test_review_marks_wrong_choice_and_weak_topics(world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    play(a, 0, correct=False)
    play(a, 1, correct=True)
    services.finish_room(room.id)
    services.set_results_visible(room.id, True)
    st = services.student_state(a.id)
    wrong = [r for r in st["review"] if not r["is_correct"]]
    assert len(wrong) == 1 and any(o["selected"] and not o["correct"] for o in wrong[0]["options"])
    assert st["weak_topics"] and st["weak_topics"][0]["wrong"] >= 1


def test_stats_topic_line_struggle_and_questions(world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    # mavzu tartibi: 1-mavzu to'g'ri, 2- va 3-mavzu xato
    for pos in range(6):
        tp = topic_of(a, pos)
        play(a, pos, correct=(tp == "O'zgaruvchilar"))
    services.finish_room(room.id)
    s = stats.stats(room)
    assert [x["topic"] for x in s["topic_line"]] == ["O'zgaruvchilar", "Sikllar", "Funksiyalar"]  # o'quv dasturi tartibi
    assert [x["error_percent"] for x in s["topic_line"]] == [0.0, 100.0, 100.0]
    assert s["class_struggle"]["topic"] == "Sikllar"
    assert s["struggle"][0]["topic"] == "Sikllar" and "Ali" in s["struggle"][0]["name"]
    assert s["topics"][0]["error_percent"] == 100.0
    assert s["questions"][0]["error_percent"] == 100.0


def test_learning_indicator_second_attempt(world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    # 1-aylana: hammasi xato; 2-aylana: hammasi to'g'ri -> hammasi o'rganildi
    for pos in range(6):
        play(a, pos, correct=False)
    for pos in range(6, 12):
        play(a, pos, correct=True)
    s = stats.stats(room)["learning"]
    assert s["repeated"] == 6 and s["learned"] == 6 and s["percent"] == 100.0
    assert s["students"][0]["percent"] == 100.0 and len(s["topics"]) == 3


def test_learning_indicator_none_without_repeats(world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    play(a, 0, correct=False)
    s = stats.stats(room)["learning"]
    assert s["repeated"] == 0 and s["percent"] is None


def test_sets_difficulty_across_rooms(client, world):
    t, cls, room, qset = world
    # ikkinchi, oson to'plam
    easy = qsets.save_set(t, qset.subject, "Faqat 1-mavzu", "topic", [qset.subject.topics.get(order=1)], 2, "equal", None,
                          list(Question.objects.filter(topic__order=1)))
    room2 = create_room_from_set(t, dict(name="R2", password="1", duration_minutes=10, interval_seconds=1), easy)
    a, b = join(room, cls, "Ali"), join(room2, cls, "Vali")
    for rm, p, ok in ((room, a, False), (room2, b, True)):
        services.start_room(rm.id)
        services.begin_participant(p.id)
        play(p, 0, correct=ok)
    res = stats.sets_difficulty(t)
    assert [r["name"] for r in res] == ["1–3-mavzular", "Faqat 1-mavzu"]  # eng qiyini birinchi
    assert res[0]["error_percent"] == 100.0 and res[1]["error_percent"] == 0.0
    assert res[0]["topics"][0]["topic"] in {"O'zgaruvchilar", "Sikllar", "Funksiyalar"}
    client.login(username="t", password="x")
    r = client.get(reverse("sets_stats"))
    assert r.status_code == 200 and "To'plamlar bo'yicha qiyinlik" in r.content.decode()


def test_stats_pages_render(client, world):
    t, cls, room, _ = world
    a = join(room, cls, "Ali")
    services.start_room(room.id)
    services.begin_participant(a.id)
    for pos in range(6):
        play(a, pos, correct=pos % 2 == 0)
    for pos in range(6, 9):
        play(a, pos)
    services.finish_room(room.id)
    client.login(username="t", password="x")
    for name in ("results", "room_stats"):
        assert client.get(reverse(name, args=[room.pk])).status_code == 200
    assert client.get(reverse("sets_stats")).status_code == 200
    page = client.get(reverse("room_stats", args=[room.pk])).content.decode()
    assert "O'rganish ko'rsatkichi" in page and "Mavzu tartibi bo'yicha" in page
    # boshqa o'qituvchi ko'ra olmaydi
    User.objects.create_user("b", password="x")
    client.login(username="b", password="x")
    assert client.get(reverse("room_stats", args=[room.pk])).status_code == 404
    assert client.get(reverse("results_export", args=[room.pk])).status_code == 404
