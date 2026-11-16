"""Excel import (3 varaq), mavzu tartibi va fan sahifalari testlari."""
import json
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from openpyxl import Workbook

from questions import services
from questions.models import Question, QuestionSet, Subject, Topic

pytestmark = pytest.mark.django_db

Q_HEAD = ["№", "Mavzu №", "Mavzu", "Savol", "Kod", "A", "B", "C", "D", "To'g'ri javob (A–D)",
          "Qiyinlik (oson/o'rta/qiyin)", "Kiritiladigan qiymatlar (input)"]


def make_xlsx(path=None, questions=None, sets=None, items=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Savollar"
    ws.append(Q_HEAD)
    for r in questions or []:
        ws.append(r)
    s = wb.create_sheet("To'plamlar")
    s.append(["To'plam №", "Nomi", "Turi (📘 Mavzu / 📚 Yig'ma / 🎲 Aralash)", "Mavzular", "Hajmi", "oson", "o'rta", "qiyin", "Savollar №"])
    for r in sets or []:
        s.append(r)
    i = wb.create_sheet("To'plam savollari")
    i.append(["To'plam №", "To'plam nomi", "Tartib", "Savol №", "Mavzu №", "Qiyinlik"])
    for r in items or []:
        i.append(r)
    b = BytesIO()
    wb.save(b)
    b.seek(0)
    if path:
        open(path, "wb").write(b.getvalue())
    return b


GOOD = [
    [1, 1, "O'zgaruvchilar", "x nima?", "x = 2\nprint(x)", "1", "2", "", "", "B", "oson", ""],
    [2, 1, "O'zgaruvchilar", "Turi?", "", "int", "str", "float", "bool", "A", "o'rta", "5"],
    [3, 2, "Sikllar", "Sikl?", "", "for", "if", "", "", "A", "qiyin", ""],
]
BAD = [
    [4, 2, "Sikllar", "", "", "a", "b", "", "", "A", "oson", ""],  # savol yo'q
    [5, 2, "Sikllar", "Bitta variant", "", "a", "", "", "", "A", "oson", ""],
    [6, 2, "Sikllar", "Noto'g'ri harf", "", "a", "b", "", "", "D", "oson", ""],  # D bo'sh
    [7, "", "", "Mavzusiz", "", "a", "b", "", "", "A", "oson", ""],
    [8, 2, "Sikllar", "Qiyinlik xato", "", "a", "b", "", "", "A", "juda", ""],
]
SETS = [[1, "1–2-mavzular", "📚 Yig'ma", "1, 2", 3, 1, 1, 1, "1, 2, 3"]]
ITEMS = [[1, "1–2-mavzular", 2, 2, 1, "o'rta"], [1, "1–2-mavzular", 1, 1, 1, "oson"], [1, "1–2-mavzular", 3, 3, 2, "qiyin"],
         [1, "1–2-mavzular", 4, 99, 2, "oson"]]


@pytest.fixture
def teacher():
    return User.objects.create_user("ustoz", password="pw12345", is_superuser=True)


def test_import_creates_subject_topics_questions_sets(teacher):
    rep = services.import_workbook(make_xlsx(questions=GOOD, sets=SETS, items=ITEMS), teacher, "Python")
    assert rep["file_error"] is None
    assert (rep["topics_created"], rep["questions_created"], rep["sets_created"]) == (2, 3, 1)
    subj = Subject.objects.get(name="Python")
    assert [(t.order, t.name) for t in subj.topics.all()] == [(1, "O'zgaruvchilar"), (2, "Sikllar")]
    q = Question.objects.get(external_no=1)
    assert q.code == "x = 2\nprint(x)" and q.options.count() == 2 and q.options.get(is_correct=True).text == "2"
    assert Question.objects.get(external_no=2).input_values == "5" and Question.objects.get(external_no=2).options.count() == 4
    qs = QuestionSet.objects.get()
    assert qs.set_type == "cumulative" and qs.size == 3
    assert [i.question.external_no for i in qs.items.all()] == [1, 2, 3]  # "Tartib" bo'yicha
    assert qs.topics.count() == 2
    # topilmagan Savol № 99 hisobotda
    assert any("99" in e["reason"] for e in rep["errors"])


def test_import_bad_rows_reported_good_saved(teacher):
    rep = services.import_workbook(make_xlsx(questions=GOOD + BAD), teacher, "Python")
    assert rep["questions_created"] == 3
    rows = sorted(e["row"] for e in rep["errors"] if e["sheet"] == "Savollar")
    assert rows == [5, 6, 7, 8, 9]  # Excel qator raqamlari (sarlavha = 1)
    reasons = " ".join(e["reason"] for e in rep["errors"])
    assert "bo'sh" in reasons and "2 ta" in reasons and "Mavzu" in reasons and "Qiyinlik" in reasons


def test_reimport_is_idempotent(teacher):
    for _ in range(2):
        rep = services.import_workbook(make_xlsx(questions=GOOD, sets=SETS, items=ITEMS), teacher, "Python")
    assert (rep["questions_created"], rep["questions_existing"]) == (0, 3)
    assert (rep["sets_created"], rep["sets_existing"], rep["topics_created"]) == (0, 1, 0)
    assert Question.objects.count() == 3 and QuestionSet.objects.count() == 1 and Topic.objects.count() == 2


def test_bad_file_and_missing_sheet(teacher):
    rep = services.import_workbook(BytesIO(b"not excel"), teacher)
    assert "Excel" in rep["file_error"]
    wb = Workbook()
    wb.active.title = "Boshqa"
    b = BytesIO()
    wb.save(b)
    b.seek(0)
    assert "Savollar" in services.import_workbook(b, teacher)["file_error"]


def test_template_roundtrip_and_export(teacher):
    rep = services.import_workbook(BytesIO(services.build_template()), teacher, "Shablon")
    assert rep["questions_created"] == 2 and rep["sets_created"] == 1 and not rep["errors"]
    subj = Subject.objects.get(name="Shablon")
    data = services.export_subject(subj)
    again = services.import_workbook(BytesIO(data), teacher, "Nusxa")
    assert again["questions_created"] == 2 and again["sets_created"] == 1 and not again["errors"]


def test_management_command(teacher, tmp_path):
    p = tmp_path / "q.xlsx"
    make_xlsx(path=str(p), questions=GOOD, sets=SETS, items=ITEMS[:3])
    call_command("import_questions", str(p), "--subject", "Python")
    assert Question.objects.count() == 3 and QuestionSet.objects.count() == 1


def test_subject_pages_and_reorder(client, teacher):
    services.import_workbook(make_xlsx(questions=GOOD), teacher, "Python")
    client.login(username="ustoz", password="pw12345")
    r = client.get(reverse("subject_list"))
    assert r.status_code == 200 and "/15 savol" in r.content.decode()  # kam savol ogohlantirishi
    subj = Subject.objects.get()
    ids = [t.pk for t in subj.topics.all()]
    r = client.post(reverse("topic_reorder", args=[subj.pk]), json.dumps({"ids": ids[::-1]}), content_type="application/json")
    assert r.json()["ok"]
    assert [t.pk for t in subj.topics.all()] == ids[::-1]
    r = client.post(reverse("topic_reorder", args=[subj.pk]), json.dumps({"ids": ids[:1]}), content_type="application/json")
    assert r.status_code == 400  # noto'g'ri ro'yxat rad etiladi
    assert client.post(reverse("topic_create", args=[subj.pk]), {"name": "Yangi"}).status_code == 302
    assert subj.topics.get(name="Yangi").order == 3
    assert client.get(reverse("subject_export", args=[subj.pk])).content[:2] == b"PK"
    User.objects.create_user("b", password="x")
    client.login(username="b", password="x")
    assert client.post(reverse("topic_reorder", args=[subj.pk]), json.dumps({"ids": ids}), content_type="application/json").status_code == 404


def test_import_page_upload(client, teacher):
    client.login(username="ustoz", password="pw12345")
    assert client.get(reverse("question_import")).status_code == 200
    f = make_xlsx(questions=GOOD + BAD, sets=SETS, items=ITEMS)
    f.name = "q.xlsx"
    r = client.post(reverse("question_import"), {"file": f, "subject_new": "Informatika"})
    assert r.status_code == 200 and r.context["report"]["questions_created"] == 3
    assert Subject.objects.filter(name="Informatika").exists()
    assert "xatoli" in r.content.decode()
