import json

import pytest
from django.core.management import call_command

from pcep import services
from pcep.management.commands.import_pcep import fingerprint, parse_item
from pcep.models import PcepAttempt, PcepAttemptAnswer, PcepModule, PcepOption, PcepQuestion


# ---------- import parser ----------
def _item(**kw):
    base = {
        "bank": "module", "module": 1, "num": 1, "section": "1.1",
        "text": "Savol?", "code": "", "type": "single",
        "options": [{"text": "a", "correct": True}, {"text": "b", "correct": False}],
    }
    base.update(kw)
    return base


def test_parser_accepts_valid_single():
    parse_item(_item())


def test_parser_accepts_multiple_with_two_correct():
    parse_item(_item(type="multiple", options=[
        {"text": "a", "correct": True}, {"text": "b", "correct": True}, {"text": "c", "correct": False}]))


@pytest.mark.parametrize("bad", [
    {"type": "matrix"},                                           # qo'llab-quvvatlanmaydigan tur
    {"text": "  "},                                               # bo'sh matn
    {"options": [{"text": "a", "correct": True}]},                # <2 variant
    {"options": [{"text": "a", "correct": False}, {"text": "b", "correct": False}]},  # to'g'ri javob yo'q
    {"options": [{"text": "a", "correct": True}, {"text": "b", "correct": True}]},    # single'da 2 ta to'g'ri
    {"type": "multiple"},                                         # multiple'da bitta to'g'ri
])
def test_parser_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_item(_item(**bad))


def test_fingerprint_same_text_code_and_bank_equal():
    assert fingerprint("module", "Q", "x=1") == fingerprint("module", "Q", "x=1")
    assert fingerprint("module", "Q", "x=1") != fingerprint("practice", "Q", "x=1")


@pytest.mark.django_db
def test_import_does_not_duplicate(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps([_item(), _item()]), encoding="utf-8")  # bir xil matn+kod
    call_command("import_pcep", str(tmp_path))
    call_command("import_pcep", str(tmp_path))                       # qayta import
    assert PcepQuestion.objects.count() == 1


# ---------- aralash test taqsimoti ----------
def test_mixed_distribution_30_is_5_9_8_8():
    assert services.mixed_distribution(30) == {1: 5, 2: 9, 3: 8, 4: 8}


@pytest.mark.parametrize("n", [10, 20, 30, 45, 60])
def test_mixed_distribution_sums_to_total(n):
    d = services.mixed_distribution(n)
    assert sum(d.values()) == n and set(d) == {1, 2, 3, 4}


# ---------- baholash ----------
@pytest.fixture
def multi_attempt(db):
    m = PcepModule.objects.create(number=1, title="M1", exam_weight=18)
    q = PcepQuestion.objects.create(bank="module", module=m, text="Select two", question_type="multiple", fingerprint="f1")
    opts = [PcepOption.objects.create(question=q, text=t, is_correct=c, order=i)
            for i, (t, c) in enumerate([("a", True), ("b", True), ("c", False), ("d", False)])]
    att = PcepAttempt.objects.create(mode="module", module=m, total=1)
    ans = PcepAttemptAnswer.objects.create(attempt=att, question=q, option_order=[o.id for o in opts])
    return att, ans, opts


def test_select_two_both_correct_is_right(multi_attempt):
    att, ans, opts = multi_attempt
    ans.selected_option_ids = [opts[0].id, opts[1].id]
    assert services.grade_answer(ans) is True


@pytest.mark.parametrize("pick", [[0], [0, 2], [0, 1, 2], [2, 3], []])
def test_select_two_partial_or_wrong_is_wrong(multi_attempt, pick):
    att, ans, opts = multi_attempt
    ans.selected_option_ids = [opts[i].id for i in pick]
    assert services.grade_answer(ans) is False


def test_finish_attempt_sets_percent_and_is_idempotent(multi_attempt):
    att, ans, opts = multi_attempt
    ans.selected_option_ids = [opts[0].id, opts[1].id]
    ans.save()
    services.finish_attempt(att)
    att.refresh_from_db()
    assert (att.correct, att.total, att.percent) == (1, 1, 100.0)
    services.finish_attempt(att)
    att.refresh_from_db()
    assert att.correct == 1


# ---------- foiz ----------
@pytest.mark.parametrize("c,t,p", [(24, 30, 80.0), (21, 30, 70.0), (0, 30, 0.0), (1, 3, 33.3), (0, 0, 0.0)])
def test_percent(c, t, p):
    assert services.percent(c, t) == p


def test_pass_threshold_is_70():
    assert services.passed(70) and not services.passed(69.9)


# ---------- brauzerga to'g'ri javob yuborilmasligi ----------
@pytest.mark.django_db
def test_correct_answers_not_sent_to_browser(client, multi_attempt):
    att, ans, opts = multi_attempt
    session = client.session
    session["pcep_attempts"] = [att.id]
    session.save()
    html = client.get(f"/pcep/attempt/{att.id}/").content.decode()
    assert "is_correct" not in html and '"correct"' not in html
    assert '"n_correct": 2' in html


# ---------- interaktiv savollar ----------
def _mk(db_q_type, interaction):
    m, _ = PcepModule.objects.get_or_create(number=1, defaults={"title": "M1", "exam_weight": 18})
    return PcepQuestion.objects.create(bank="module", module=m, text="Q", question_type=db_q_type,
                                       interaction=interaction, fingerprint=f"fp-{db_q_type}-{PcepQuestion.objects.count()}")


MATCH = {"items": [{"id": "i1", "text": "Integer"}, {"id": "i2", "text": "Float"}, {"id": "i3", "text": "String"}],
         "targets": [{"id": "t1", "text": "1"}, {"id": "t2", "text": "1.0"}, {"id": "t3", "text": '"1"'}],
         "answer": {"t1": "i1", "t2": "i2", "t3": "i3"}}
ORDER = {"items": [{"id": "i1", "text": "A"}, {"id": "i2", "text": "B"}, {"id": "i3", "text": "C"}], "answer": ["i2", "i1", "i3"]}
CAT = {"items": [{"id": "i1", "text": "a"}, {"id": "i2", "text": "for"}, {"id": "p1", "text": "_x"}],
       "categories": [{"id": "c1", "label": "ok"}, {"id": "c2", "label": "bad"}], "prefilled": {"p1": "c1"},
       "answer": {"i1": "c1", "i2": "c2", "p1": "c1"}}
GAP = {"template": "x = {{g1}}{{g2}}", "blocks": [{"id": "b1", "text": "int("}, {"id": "b2", "text": "1)"}, {"id": "b3", "text": "float("}],
       "answer": {"g1": "b1", "g2": "b2"}, "alternatives": [{"g1": "b3", "g2": "b2"}], "solution": "x = int(1)"}

CASES = [
    # (tur, interaksiya, to'g'ri, qisman, bo'sh, alternativ)
    ("match", MATCH, {"slots": MATCH["answer"]}, {"slots": {"t1": "i1", "t2": "i3", "t3": "i2"}}, {}, None),
    ("order", ORDER, {"order": ORDER["answer"]}, {"order": ["i2", "i3", "i1"]}, {}, None),
    ("categorize", CAT, {"slots": {"i1": "c1", "i2": "c2"}}, {"slots": {"i1": "c1", "i2": "c1"}}, {}, None),
    ("code_gap", GAP, {"slots": {"g1": "b1", "g2": "b2"}}, {"slots": {"g1": "b1"}}, {}, {"slots": {"g1": "b3", "g2": "b2"}}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("qt,ix,right,partial,empty,alt", CASES)
def test_interactive_grading(qt, ix, right, partial, empty, alt):
    q = _mk(qt, ix)
    assert services.interactive_correct(q, right) is True            # to'g'ri
    assert services.interactive_correct(q, partial) is False         # qisman to'g'ri — ball yo'q
    assert services.interactive_correct(q, empty) is False           # bo'sh
    if alt:
        assert services.interactive_correct(q, alt) is True          # alternativ javob
    rep = services.slot_report(q, partial)
    assert 0 <= rep["ok"] < rep["total"] or qt == "categorize"       # qisman natija hisoblanadi
    assert services.slot_report(q, right)["ok"] == services.slot_report(q, right)["total"]


@pytest.mark.django_db
def test_partial_report_counts_slots():
    q = _mk("match", MATCH)
    rep = services.slot_report(q, {"slots": {"t1": "i1", "t2": "i3", "t3": "i2"}})
    assert (rep["ok"], rep["total"]) == (1, 3)


@pytest.mark.django_db
def test_same_block_in_two_slots_is_wrong():
    q = _mk("code_gap", GAP)
    assert services.interactive_correct(q, {"slots": {"g1": "b1", "g2": "b1"}}) is False


@pytest.mark.django_db
def test_sanitize_rejects_foreign_ids_and_duplicates():
    q = _mk("code_gap", GAP)
    assert services.sanitize_response(q, {"slots": {"g1": "b1", "g2": "b1"}}) is None        # bir blok 2 katakka
    assert services.sanitize_response(q, {"slots": {"g9": "b1"}}) == {"slots": {}}            # begona katak tashlab yuboriladi
    assert services.sanitize_response(_mk("order", ORDER), {"order": ["i1", "i2"]}) is None   # to'liq emas


@pytest.mark.django_db
def test_is_answered_requires_all_slots():
    q = _mk("code_gap", GAP)
    assert not services.is_answered(q, {"slots": {"g1": "b1"}})
    assert services.is_answered(q, {"slots": {"g1": "b1", "g2": "b2"}})


@pytest.mark.django_db
def test_interactive_correct_answers_not_sent_to_browser(client):
    q = _mk("code_gap", GAP)
    att = PcepAttempt.objects.create(mode="module", module=q.module, total=1)
    PcepAttemptAnswer.objects.create(attempt=att, question=q, option_order=["b3", "b1", "b2"])
    s = client.session
    s["pcep_attempts"] = [att.id]
    s.save()
    html = client.get(f"/pcep/attempt/{att.id}/").content.decode()
    assert '"answer"' not in html and '"alternatives"' not in html and '"solution"' not in html


@pytest.mark.django_db
def test_import_produces_37_interactive_questions():
    from pathlib import Path
    data = Path(__file__).resolve().parent / "data"
    call_command("import_pcep", str(data))
    call_command("import_pcep", str(data))     # qayta import — takror yaratmasligi kerak
    inter = PcepQuestion.objects.filter(question_type__in=PcepQuestion.INTERACTIVE)
    assert inter.count() == 37
    assert dict(sorted({t: inter.filter(question_type=t).count() for t in PcepQuestion.INTERACTIVE}.items())) == {
        "categorize": 1, "code_gap": 28, "match": 4, "order": 4}
    assert PcepOption.objects.filter(question__in=inter).count() == 0       # eski noto'g'ri variantlar o'chirilgan
    assert not inter.filter(verified=False).exists()                         # hammasi tekshiruvdan o'tgan
    assert PcepQuestion.objects.count() == 122
