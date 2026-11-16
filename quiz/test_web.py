"""HTTP sahifalar, Excel import va WebSocket oqimi uchun testlar."""
import json
import uuid
from io import BytesIO

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.urls import reverse
from openpyxl import Workbook

from questions.models import Question, QuestionSet, SchoolClass, Topic
from questions import sets
from quiz import services
from rooms.models import Room
from rooms.services import create_room_with_questions

from .tests import make_questions

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher_client(client):
    u = User.objects.create_user("ustoz", password="pw12345")
    client.login(username="ustoz", password="pw12345")
    return client, u


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = BytesIO()
    wb.save(b)
    b.seek(0)
    b.name = "q.xlsx"
    return b


def test_template_download(teacher_client):
    client, _ = teacher_client
    r = client.get(reverse("import_template"))
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_question_create_validation(teacher_client):
    client, user = teacher_client
    r = client.post(reverse("question_create"), {"text": "S", "topic": "T", "opt_text": ["a", ""], "correct": "0"})
    assert r.status_code == 200 and not Question.objects.exists()  # 2 tadan kam
    r = client.post(
        reverse("question_create"),
        {"text": "S", "topic": "T", "difficulty": "easy", "opt_text": ["a", "b", "c"], "correct": "2"},
    )
    assert r.status_code == 302
    q = Question.objects.get()
    assert q.options.get(is_correct=True).text == "c"


def test_teacher_pages_and_room_flow(teacher_client):
    client, user = teacher_client
    qs = make_questions(user, 3)
    SchoolClass.objects.create(name="7-A")
    qset = sets.save_set(user, qs[0].topic.subject, "To'plam", "topic", [qs[0].topic], 3, "equal", None, qs)
    for name in ("dashboard", "question_list", "question_create", "question_import", "classes", "room_create", "room_list", "results_list", "stats_list", "settings", "password_change"):
        assert client.get(reverse(name)).status_code == 200, name
    r = client.post(
        reverse("room_create"),
        {
            "name": "Xona 1", "password": "abc", "duration_minutes": 15, "interval_seconds": 3,
            "powerups_enabled": "on", "steal_enabled": "on", "freeze_enabled": "on",
            "steal_min_percent": 5, "steal_max_percent": 20, "freeze_min_seconds": 5, "freeze_max_seconds": 15,
            "grade_5": 86, "grade_4": 71, "grade_3": 56, "question_set": qset.pk,
        },
    )
    assert r.status_code == 302 and "/tayyor/" in r["Location"]
    room = Room.objects.get()
    assert len(room.code) == 6 and room.check_password("abc") and room.room_questions.count() == 3
    assert room.question_set_id == qset.pk and (room.steal_min_percent, room.steal_max_percent) == (5, 20)
    assert (room.freeze_min_seconds, room.freeze_max_seconds) == (5, 15)
    qset.refresh_from_db()
    assert qset.last_used_at is not None
    assert room.room_questions.first().snapshot["topic_order"] == qs[0].topic.order
    for name in ("room_control", "room_screen", "results", "room_stats", "room_ready"):
        assert client.get(reverse(name, args=[room.pk])).status_code == 200, name
    for name in ("dashboard", "question_list", "room_list", "results_list", "stats_list"):
        assert client.get(reverse(name)).status_code == 200, name
    assert client.get(reverse("question_edit", args=[qs[0].pk])).status_code == 200
    assert client.get(reverse("question_list") + "?topic=1&q=Savol&difficulty=medium").status_code == 200
    Room.objects.filter(pk=room.pk).update(status="finished")
    assert client.get(reverse("results_list")).status_code == 200
    assert client.post(reverse("room_results_visible", args=[room.pk]), {"value": "1"}).status_code == 302
    room.refresh_from_db()
    assert room.results_visible
    assert client.get(reverse("room_qr", args=[room.pk]))["Content-Type"] == "image/png"
    assert client.get(reverse("results_export", args=[room.pk])).content[:2] == b"PK"


def test_other_teacher_cannot_open_room(client):
    a = User.objects.create_user("a", password="x")
    User.objects.create_user("b", password="x")
    room = create_room_with_questions(a, dict(name="R", password="1"), make_questions(a, 1))
    client.login(username="b", password="x")
    assert client.get(reverse("room_control", args=[room.pk])).status_code == 404


def test_join_api_sets_cookie_and_token(client):
    t = User.objects.create_user("t", password="x")
    room = create_room_with_questions(t, dict(name="R", password="pw"), make_questions(t, 2))
    cls = SchoolClass.objects.create(name="5-A")
    body = dict(code=room.code, password="pw", first_name="Ali", last_name="Vali", school_class=cls.id, avatar="a01")
    r = client.post(reverse("join_api"), json.dumps(body), content_type="application/json")
    assert r.json()["ok"] and r.cookies["pt"].value == r.json()["token"]
    # bir xil ism-familiya ikkinchi marta kira oladi, token boshqa
    r2 = client.post(reverse("join_api"), json.dumps(body), content_type="application/json")
    assert r2.json()["token"] != r.json()["token"]
    bad = client.post(reverse("join_api"), json.dumps({**body, "password": "x"}), content_type="application/json")
    assert bad.status_code == 400


def test_student_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/kirish/123456/").status_code == 200
    assert client.get("/play/").status_code == 200


# ---------------------------------------------------------------- WebSocket
def ws_app():
    from config.asgi import application

    return application


def student_comm(token, cookie=None):
    headers = [(b"origin", b"http://localhost"), (b"host", b"localhost")]
    if cookie is not False:
        headers.append((b"cookie", f"pt={cookie or token}".encode()))
    return WebsocketCommunicator(ws_app(), f"/ws/student/?t={token}", headers=headers)


@pytest.mark.django_db(transaction=True)
def test_websocket_token_cookie_required():
    t = User.objects.create_user("t", password="x")
    room = create_room_with_questions(t, dict(name="R", password="pw"), make_questions(t, 2))
    cls = SchoolClass.objects.create(name="5-A")
    p = services.join_room(room.code, "pw", "A", "B", cls.id, "a01")

    async def run():
        ok = student_comm(p.session_token)
        connected, _ = await ok.connect()
        assert connected
        state = await ok.receive_json_from()
        assert state["phase"] == "lobby"
        await ok.disconnect()
        # cookie yo'q (boshqa brauzer) -> rad etiladi
        other = student_comm(p.session_token, cookie=False)
        connected, _ = await other.connect()
        assert not connected
        # noto'g'ri token
        bad = student_comm("yoq-token")
        connected, _ = await bad.connect()
        assert not connected

    async_to_sync(run)()


@pytest.mark.django_db(transaction=True)
def test_websocket_full_flow():
    t = User.objects.create_user("t", password="x")
    qs = make_questions(t, 2)
    room = create_room_with_questions(t, dict(name="R", password="pw", interval_seconds=1), qs)
    cls = SchoolClass.objects.create(name="5-A")
    p = services.join_room(room.code, "pw", "A", "B", cls.id, "a01")

    async def run():
        c = student_comm(p.session_token)
        await c.connect()
        assert (await c.receive_json_from())["phase"] == "lobby"
        from channels.db import database_sync_to_async as db

        await db(services.start_room)(room.id)
        assert (await c.receive_json_from())["phase"] == "ready"
        await c.send_json_to({"t": "begin"})
        st = await c.receive_json_from()
        assert st["phase"] == "question"
        await c.send_json_to({"t": "next"})
        q = await c.receive_json_from()
        assert q["t"] == "question" and len(q["options"]) == 4 and "is_correct" not in json.dumps(q)
        # xato variant yuborish: server baholaydi
        await c.send_json_to({"t": "answer", "position": 0, "option_id": q["options"][0]["id"], "uuid": str(uuid.uuid4())})
        res = await c.receive_json_from()
        assert res["t"] == "answer_result" and "correct" in res
        # qoidabuzarlik -> qulflanadi
        await c.send_json_to({"t": "next"})
        await c.receive_json_from()
        await c.send_json_to({"t": "violation", "type": "tab_switch"})
        st = await c.receive_json_from()
        assert st["phase"] == "locked"
        await c.disconnect()

    async_to_sync(run)()


def test_room_create_validation_and_inline_set(teacher_client):
    client, user = teacher_client
    qs = make_questions(user, 12)
    topic = qs[0].topic
    base = {
        "name": "X", "password": "abc", "duration_minutes": 10, "interval_seconds": 3,
        "steal_min_percent": 5, "steal_max_percent": 20, "freeze_min_seconds": 5, "freeze_max_seconds": 15,
        "grade_5": 86, "grade_4": 71, "grade_3": 56,
    }
    # to'plamsiz
    assert client.post(reverse("room_create"), base).status_code == 200 and not Room.objects.exists()
    qset = sets.save_set(user, topic.subject, "T", "topic", [topic], 12, "equal", None, qs)
    # teskari oraliq
    bad = {**base, "question_set": qset.pk, "steal_min_percent": 30, "steal_max_percent": 10}
    assert client.post(reverse("room_create"), bad).status_code == 200 and not Room.objects.exists()
    bad = {**base, "question_set": qset.pk, "freeze_min_seconds": 20, "freeze_max_seconds": 10}
    assert client.post(reverse("room_create"), bad).status_code == 200 and not Room.objects.exists()
    # boshqa o'qituvchining to'plami ishlatilmaydi
    other = User.objects.create_user("b", password="x")
    foreign = sets.save_set(other, topic.subject, "F", "topic", [topic], 12, "equal", None, qs)
    assert client.post(reverse("room_create"), {**base, "question_set": foreign.pk}).status_code == 200
    assert not Room.objects.exists()
    # ?set= oldindan tanlaydi
    assert client.get(reverse("room_create") + f"?set={qset.pk}").context["selected"] == qset.pk
    # sehrgar ichidan tezkor generatsiya (JSON)
    r = client.post(reverse("set_generate"), {"subject": topic.subject.pk, "set_type": "topic", "topic": topic.pk, "size": 10,
                                               "distribution": "equal"}, HTTP_X_REQUESTED_WITH="fetch")
    d = r.json()
    assert d["ok"] and d["count"] == 10 and QuestionSet.objects.get(pk=d["id"]).teacher == user
    r = client.post(reverse("set_generate"), {"subject": topic.subject.pk, "set_type": "mixed", "size": 10}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 400 and not r.json()["ok"]
    # xonani yaratish va snapshot to'plam o'zgarsa ham saqlanadi
    r = client.post(reverse("room_create"), {**base, "question_set": qset.pk})
    room = Room.objects.get()
    assert r.status_code == 302 and room.room_questions.count() == 12
    qs[0].text = "O'ZGARDI"
    qs[0].save()
    assert "O'ZGARDI" not in str([rq.snapshot["text"] for rq in room.room_questions.all()])


@pytest.mark.django_db(transaction=True)
def test_projector_consumer_owner_only_and_readonly():
    from quiz.consumers import ProjectorConsumer

    owner = User.objects.create_user("own", password="x")
    other = User.objects.create_user("oth", password="x")
    room = create_room_with_questions(owner, dict(name="R", password="pw"), make_questions(owner, 2))

    def comm(user):
        c = WebsocketCommunicator(ProjectorConsumer.as_asgi(), f"/ws/projector/{room.id}/")
        c.scope["url_route"] = {"kwargs": {"room_id": room.id}}
        c.scope["user"] = user
        return c

    async def run():
        from django.contrib.auth.models import AnonymousUser

        for bad in (other, AnonymousUser()):
            ok, _ = await comm(bad).connect()
            assert not ok
        c = comm(owner)
        ok, _ = await c.connect()
        assert ok
        snap = await c.receive_json_from()
        assert snap["t"] == "snapshot" and snap["room"]["code"] == room.code and snap["violations"] == []
        # boshqaruv buyrug'i ishlamaydi
        await c.send_json_to({"t": "start"})
        assert await c.receive_nothing(timeout=0.3)
        await c.disconnect()

    async_to_sync(run)()
    room.refresh_from_db()
    assert room.status == "waiting"


@pytest.mark.django_db(transaction=True)
def test_ws_ping_returns_time_sync_and_clock_loop_finishes_room():
    from quiz.consumers import _check_clock

    t = User.objects.create_user("t", password="x")
    room = create_room_with_questions(t, dict(name="R", password="pw"), make_questions(t, 2))
    cls = SchoolClass.objects.create(name="5-A")
    p = services.join_room(room.code, "pw", "A", "B", cls.id, "a01")

    async def run():
        from channels.db import database_sync_to_async as db

        c = student_comm(p.session_token)
        await c.connect()
        await c.receive_json_from()
        await c.send_json_to({"t": "ping"})
        pong = await c.receive_json_from()
        assert pong["t"] == "pong" and pong["status"] == "waiting"
        await db(services.start_room)(room.id)
        await c.receive_json_from()  # ready holati
        await db(lambda: Room.objects.filter(pk=room.id).update(ends_at=services.timezone.now() - services.timedelta(seconds=1)))()
        await db(_check_clock)(room.id)  # fon soati vaqti tugagan xonani yakunlaydi
        assert (await db(lambda: Room.objects.get(pk=room.id).status)()) == "finished"
        await c.disconnect()

    async_to_sync(run)()


@pytest.mark.django_db(transaction=True)
def test_websocket_powerup_server_picks_target_and_victim_is_notified():
    from channels.db import database_sync_to_async as db
    from quiz.models import Participant, PowerUpCode

    t = User.objects.create_user("t", password="x")
    room = create_room_with_questions(t, dict(name="R", password="pw", interval_seconds=1), make_questions(t, 2))
    cls = SchoolClass.objects.create(name="5-A")
    a = services.join_room(room.code, "pw", "Ali", "A", cls.id, "a01")
    b = services.join_room(room.code, "pw", "Vali", "B", cls.id, "a02")

    async def run():
        ca, cb = student_comm(a.session_token), student_comm(b.session_token)
        await ca.connect(); await cb.connect()
        await ca.receive_json_from(); await cb.receive_json_from()
        await db(services.start_room)(room.id)
        await db(lambda: [services.begin_participant(p.id) for p in (a, b)])()
        await db(lambda: Participant.objects.filter(pk=b.pk).update(score=1000))()
        await db(lambda: PowerUpCode.objects.create(participant=a, code="ABCD1234"))()
        # mijoz "target" yuborsa ham e'tiborsiz qoladi: server o'zi tanlaydi
        await ca.send_json_to({"t": "powerup", "code": "ABCD1234", "kind": "steal", "target": 999999})
        res = None
        for _ in range(6):
            m = await ca.receive_json_from()
            if m.get("t") == "powerup_result":
                res = m
                break
        assert res and res["target"]["id"] == b.id and 50 <= res["amount"] <= 200
        assert res["reel"] and all(set(r) == {"id", "name", "avatar"} for r in res["reel"])
        note = None
        for _ in range(6):
            m = await cb.receive_json_from()
            if m.get("t") == "notice":
                note = m
                break
        assert note and note["kind"] == "steal" and note["text"] == f"💰 Ali sendan {res['amount']} ball oldi!"
        await ca.disconnect(); await cb.disconnect()

    async_to_sync(run)()
