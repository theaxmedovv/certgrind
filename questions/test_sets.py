"""To'plam generatori, avtomatik zinapoya va kutubxona testlari."""
import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from questions import sets
from questions.models import Question, QuestionOption, QuestionSet, Subject, Topic

pytestmark = pytest.mark.django_db
DIFFS = ["easy", "medium", "hard"]


@pytest.fixture
def teacher():
    return User.objects.create_user("ustoz", password="pw12345")


def make_subject(teacher, per_topic=(20, 20, 20, 20, 20, 20), name="Python"):
    subj = Subject.objects.create(teacher=teacher, name=name)
    topics = []
    for i, n in enumerate(per_topic, 1):
        t = Topic.objects.create(teacher=teacher, subject=subj, name=f"Mavzu {i}", order=i)
        topics.append(t)
        for j in range(n):
            q = Question.objects.create(teacher=teacher, topic=t, text=f"M{i} S{j}",
                                        difficulty=DIFFS[j % 3 if j % 10 < 3 else (1 if j % 10 < 8 else 2)])
            QuestionOption.objects.create(question=q, text="a", is_correct=True)
            QuestionOption.objects.create(question=q, text="b")
    return subj, topics


def test_split_sums_exactly():
    for total in (10, 15, 25, 37, 60):
        for w in ([1, 1, 1], [3, 0, 7], [60, 40], [1]):
            assert sum(sets.split(total, w)) == total
    assert sets.split(0, [1, 1]) == [0, 0]


def alloc(topics, total, method="equal", locks=None, rng=None):
    avail = [(t.pk, t.questions.count()) for t in topics]
    return sets.allocate(avail, total, method, locks, rng)["counts"]


def test_allocate_distributions(teacher):
    _, topics = make_subject(teacher, (30, 30, 30, 30))
    assert sorted(alloc(topics, 24).values()) == [6, 6, 6, 6]
    c = alloc(topics, 50, "latest_focus")  # oxirgi 40% = 20, qolgan 30 teng
    assert c[topics[-1].pk] == 20 and sum(c.values()) == 50 and sorted(c.values())[:3] == [10, 10, 10]
    _, topics = make_subject(teacher, (10, 30, 20), name="Boshqa")
    c = alloc(topics, 30, "proportional")
    assert [c[t.pk] for t in topics] == [5, 15, 10]


@pytest.mark.parametrize("total,k", [(100, 7), (37, 5), (10, 15), (10, 10), (55, 3), (100, 1)])
@pytest.mark.parametrize("method", ["equal", "proportional", "latest_focus", "random"])
def test_allocation_sum_always_exact(teacher, total, k, method):
    _, topics = make_subject(teacher, (20,) * k, name=f"F{total}-{k}-{method}")
    c = alloc(topics, total, method)
    assert sum(c.values()) == min(total, 20 * k)
    assert all(0 <= c[t.pk] <= 20 for t in topics)
    if method != "random" and total >= k:
        assert min(c.values()) >= 1  # hech bir mavzu 0 ta olmaydi
    if method != "random" and total < k:
        assert max(c.values()) == 1 and sum(1 for v in c.values() if v) == total


def test_equal_remainder_goes_to_random_topics(teacher):
    _, topics = make_subject(teacher, (30,) * 7)
    seen = set()
    for _ in range(12):
        c = alloc(topics, 100)
        assert sorted(c.values()) == [14] * 5 + [15] * 2  # 100 / 7 = 14 x 7 + 2 qoldiq
        seen.add(tuple(t.pk for t in topics if c[t.pk] == 15))
    assert len(seen) > 1  # qoldiq har safar boshqa mavzularga tushadi


def test_shortage_spills_over_to_other_topics(teacher):
    _, topics = make_subject(teacher, (12, 40, 40))
    c = alloc(topics, 45)  # teng: 15 dan, lekin 1-mavzuda 12 ta bor
    assert c[topics[0].pk] == 12 and sum(c.values()) == 45 and sorted(c.values())[1:] == [16, 17]
    c = alloc(topics, 200)  # bazada jami 92 ta
    assert [c[t.pk] for t in topics] == [12, 40, 40]
    _, topics = make_subject(teacher, (1, 100, 100), name="Kichik")
    for method in ("proportional", "latest_focus", "equal"):
        c = alloc(topics, 30, method)
        assert sum(c.values()) == 30 and min(c.values()) >= 1


def test_locks_keep_value_and_infeasible_locks_dropped(teacher):
    _, topics = make_subject(teacher, (20, 20, 20, 20))
    a = topics[0].pk
    avail = [(t.pk, 20) for t in topics]
    res = sets.allocate(avail, 40, "equal", {a: 15})
    assert res["counts"][a] == 15 and sum(res["counts"].values()) == 40 and not res["locks_dropped"]
    res = sets.allocate(avail, 10, "equal", {a: 15})  # 15 > 10: qulf ishlamaydi
    assert res["locks_dropped"] and sum(res["counts"].values()) == 10
    res = sets.allocate(avail, 80, "equal", {a: 5})  # qolganlar 75 ga sig'maydi (3 x 20 = 60)
    assert res["locks_dropped"] and sum(res["counts"].values()) == 80


def test_manual_adjust_keeps_total_and_locks(teacher):
    _, topics = make_subject(teacher, (20, 20, 20, 20))
    ids = [t.pk for t in topics]
    avail = {i: 20 for i in ids}
    counts = {i: 10 for i in ids}
    out, locks = sets.adjust_counts(avail, counts, set(), ids[0], 16)
    assert out[ids[0]] == 16 and sum(out.values()) == 40 and locks == {ids[0]}
    assert sorted(out[i] for i in ids[1:]) == [8, 8, 8]
    # ikkinchisini ham qo'lda o'zgartirsak, birinchisi (qulflangan) o'zgarmaydi
    out2, locks2 = sets.adjust_counts(avail, out, locks, ids[1], 4)
    assert out2[ids[0]] == 16 and out2[ids[1]] == 4 and sum(out2.values()) == 40 and locks2 == {ids[0], ids[1]}
    # kamaytirish: farq boshqalarga qo'shiladi, lekin 20 dan oshmaydi
    out3, _ = sets.adjust_counts(avail, {ids[0]: 20, ids[1]: 20, ids[2]: 1, ids[3]: 1}, set(), ids[0], 1)
    assert sum(out3.values()) == 42 and max(out3.values()) <= 20
    # boshqalar sig'dira olmasa o'zgartirish chegaralanadi (yig'indi saqlanadi)
    full = {ids[0]: 10, ids[1]: 20, ids[2]: 20, ids[3]: 20}
    out4, _ = sets.adjust_counts(avail, full, set(), ids[0], 2)
    assert out4[ids[0]] == 10 and sum(out4.values()) == 70
    # hech bir mavzu 0 ga tushmaydi
    out5, _ = sets.adjust_counts(avail, counts, set(), ids[0], 20)
    assert min(out5.values()) >= 1 and sum(out5.values()) == 40


def test_difficulty_plan_fills_from_other_difficulties():
    mix = {"easy": 30, "medium": 50, "hard": 20}
    assert sets.difficulty_plan(10, {"easy": 10, "medium": 10, "hard": 10}, mix) == {"easy": 3, "medium": 5, "hard": 2}
    p = sets.difficulty_plan(10, {"easy": 1, "medium": 1, "hard": 20}, mix)
    assert p == {"easy": 1, "medium": 1, "hard": 8}  # oson/o'rta yetmadi — qiyindan to'ldirildi
    assert sum(sets.difficulty_plan(50, {"easy": 3, "medium": 3, "hard": 3}, None).values()) == 9


def test_generate_unique_exact_size_and_mix(teacher):
    _, topics = make_subject(teacher)
    for _ in range(5):
        qs, short = sets.generate(topics, 30, "equal", {"easy": 30, "medium": 50, "hard": 20})
        assert short == 0 and len(qs) == 30 and len({q.pk for q in qs}) == 30
        per = {}
        for q in qs:
            per[q.topic_id] = per.get(q.topic_id, 0) + 1
        assert set(per.values()) == {5}


def test_generate_is_random(teacher):
    _, topics = make_subject(teacher)
    runs = {tuple(sorted(q.pk for q in sets.generate(topics, 15)[0])) for _ in range(6)}
    assert len(runs) > 1


def test_generate_redistributes_shortage(teacher):
    _, topics = make_subject(teacher, (3, 30))
    qs, short = sets.generate(topics, 20, "equal")  # 1-mavzuda 3 ta: qolgan 17 ta ikkinchisidan
    assert len(qs) == 20 and short == 0 and len({q.pk for q in qs}) == 20
    qs, short = sets.generate(topics, 40, "equal")  # bazada jami 33 ta
    assert len(qs) == 33 and short == 7


def test_generate_uses_given_counts_when_valid(teacher):
    _, topics = make_subject(teacher, (20, 20, 20))
    want = {topics[0].pk: 15, topics[1].pk: 3, topics[2].pk: 2}
    qs, _ = sets.generate(topics, 20, "equal", counts=want)
    got = {}
    for q in qs:
        got[q.topic_id] = got.get(q.topic_id, 0) + 1
    assert got == want
    qs, _ = sets.generate(topics, 20, "equal", counts={topics[0].pk: 20})  # noto'g'ri — qayta hisoblanadi
    assert len(qs) == 20 and len({q.topic_id for q in qs}) == 3


def test_random_method_samples_whole_pool(teacher):
    _, topics = make_subject(teacher, (5, 40, 5))
    qs, short = sets.generate(topics, 30, "random")
    assert len(qs) == 30 and short == 0 and len({q.pk for q in qs}) == 30


def test_difficulty_mix_respected_when_enough(teacher):
    _, topics = make_subject(teacher, (60,))
    qs, _ = sets.generate(topics, 20, "equal", {"easy": 0, "medium": 100, "hard": 0})
    counts = {d: sum(1 for q in qs if q.difficulty == d) for d in DIFFS}
    assert Question.objects.filter(difficulty="medium").count() >= 20
    assert counts["medium"] == 20


def test_suggest_name(teacher):
    _, topics = make_subject(teacher, (5, 5, 5, 5, 5))
    assert sets.suggest_name("cumulative", topics, 25) == "1–5-mavzular (25 ta)"
    assert sets.suggest_name("topic", topics[:1], 15) == "Mavzu 1 (15 ta)"
    assert sets.suggest_name("mixed", [topics[0], topics[3]], 20).startswith("Aralash: Mavzu 1, Mavzu 4")


def test_auto_create_all_ladder_and_idempotent(teacher):
    subj, topics = make_subject(teacher, (20,) * 6)
    res = sets.auto_create_all(teacher, subj)
    qsets = QuestionSet.objects.filter(subject=subj)
    topic_sets = qsets.filter(set_type="topic")
    cum = qsets.filter(set_type="cumulative")
    assert topic_sets.count() == 6 and all(s.items.count() == 15 for s in topic_sets)
    # 6 ta mavzu: zinapoya 1–2 (10), 1–3 (15), 1–4 (20), 1–5 (25), 1–6 (30) va barcha mavzular → 100
    assert sorted(s.size for s in cum) == [10, 15, 20, 25, 30, 100]
    assert all(s.items.count() == s.size for s in qsets)
    assert res["created"] == 12
    res2 = sets.auto_create_all(teacher, subj)
    assert res2["created"] == 0 and res2["skipped"] == 12 and QuestionSet.objects.count() == 12


def test_library_and_flow(client, teacher):
    subj, topics = make_subject(teacher, (20, 20, 20))
    client.login(username="ustoz", password="pw12345")
    assert client.get(reverse("set_list")).status_code == 200
    assert client.get(reverse("set_generate")).status_code == 200
    r = client.post(reverse("set_generate"), {
        "subject": subj.pk, "set_type": "cumulative", "upto": 3, "size": 25, "distribution": "latest_focus",
        "mix_easy": 30, "mix_medium": 50, "mix_hard": 20, "name": "",
    })
    assert r.status_code == 302
    qset = QuestionSet.objects.get()
    assert qset.name == "1–3-mavzular (25 ta)" and qset.items.count() == 25 and qset.topics.count() == 3
    assert client.get(reverse("set_detail", args=[qset.pk])).status_code == 200
    before = {i.question_id for i in qset.items.all()}
    client.post(reverse("set_reshuffle", args=[qset.pk]))
    assert qset.items.count() == 25
    item = qset.items.first()
    old_q = item.question_id
    client.post(reverse("set_item_replace", args=[qset.pk, item.pk]))
    item.refresh_from_db()
    assert item.question_id != old_q and qset.items.values("question").distinct().count() == 25
    client.post(reverse("set_item_remove", args=[qset.pk, item.pk]))
    assert qset.items.count() == 24 and [i.order for i in qset.items.all()] == list(range(1, 25))
    r = client.post(reverse("set_copy", args=[qset.pk]))
    assert QuestionSet.objects.count() == 2
    assert client.get(reverse("set_export", args=[qset.pk])).content[:2] == b"PK"
    assert client.get(reverse("set_list") + f"?type=cumulative&size=25&subject={subj.pk}&topic={topics[0].pk}").status_code == 200
    client.post(reverse("set_delete", args=[qset.pk]))
    assert QuestionSet.objects.count() == 1


def test_generate_validation_and_isolation(client, teacher):
    subj, _ = make_subject(teacher, (20, 20))
    client.login(username="ustoz", password="pw12345")
    r = client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "cumulative", "upto": 1, "size": 5})
    assert r.status_code == 200 and not QuestionSet.objects.exists()  # xato: hajm va mavzular
    client.post(reverse("set_auto_all"), {"subject": subj.pk})
    s = QuestionSet.objects.first()
    User.objects.create_user("b", password="x")
    client.login(username="b", password="x")
    assert client.get(reverse("set_detail", args=[s.pk])).status_code == 404
    assert client.post(reverse("set_delete", args=[s.pk])).status_code == 404


def per_topic_of(qset):
    out = {}
    for it in qset.items.select_related("question"):
        out[it.question.topic_id] = out.get(it.question.topic_id, 0) + 1
    return out


def test_size_limits_10_and_100(client, teacher):
    subj, topics = make_subject(teacher, (20,) * 6)
    client.login(username="ustoz", password="pw12345")
    ids = [t.pk for t in topics]
    for size in (10, 100):
        r = client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": ids, "size": size})
        assert r.status_code == 302
        assert QuestionSet.objects.order_by("-id").first().items.count() == size
    n = QuestionSet.objects.count()
    for bad in (9, 101, 500, 0, -5):
        r = client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": ids, "size": bad})
        assert r.status_code == 200 and QuestionSet.objects.count() == n  # rad etildi
    r = client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": ids, "size": 101},
                    HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 400 and "100" in r.json()["errors"][0]


def test_generate_with_manual_allocation_and_reshuffle_keeps_it(client, teacher):
    subj, topics = make_subject(teacher, (20, 20, 20))
    client.login(username="ustoz", password="pw12345")
    ids = [t.pk for t in topics]
    alloc_ = {str(ids[0]): 12, str(ids[1]): 5, str(ids[2]): 3}
    client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": ids, "size": 20,
                                           "distribution": "equal", "alloc": json.dumps(alloc_)})
    qset = QuestionSet.objects.get()
    assert per_topic_of(qset) == {ids[0]: 12, ids[1]: 5, ids[2]: 3}
    client.post(reverse("set_reshuffle", args=[qset.pk]))
    assert per_topic_of(qset) == {ids[0]: 12, ids[1]: 5, ids[2]: 3}
    # noto'g'ri alloc (yig'indi mos emas) e'tiborsiz — teng taqsimot
    client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": ids, "size": 21,
                                           "alloc": json.dumps({str(ids[0]): 21})})
    assert sorted(per_topic_of(QuestionSet.objects.order_by("-id").first()).values()) == [7, 7, 7]


def test_shortage_banner_when_database_is_small(client, teacher):
    subj, topics = make_subject(teacher, (3, 10))
    client.login(username="ustoz", password="pw12345")
    client.post(reverse("set_generate"), {"subject": subj.pk, "set_type": "mixed", "topics": [t.pk for t in topics], "size": 20})
    qset = QuestionSet.objects.get()
    assert qset.items.count() == 13
    assert "yetmadi" in client.get(reverse("set_detail", args=[qset.pk])).content.decode()


def plan(client, **body):
    return client.post(reverse("set_plan"), json.dumps(body), content_type="application/json")


def test_plan_endpoint_live_recalculation(client, teacher):
    subj, topics = make_subject(teacher, (30,) * 7)
    client.login(username="ustoz", password="pw12345")
    ids = [t.pk for t in topics]
    r = plan(client, subject=subj.pk, topics=ids, size=100, method="equal", seed=7)
    d = r.json()
    assert r.status_code == 200 and d["ok"] and d["effective"] == 100 and d["total_avail"] == 210
    assert sum(x["n"] for x in d["rows"]) == 100 and sorted(x["n"] for x in d["rows"]) == [14] * 5 + [15] * 2
    assert all(x["easy"] + x["medium"] + x["hard"] == x["n"] for x in d["rows"])
    assert sum(d["totals"].values()) == 100
    # bir xil seed — bir xil natija (sahifa "sakramaydi")
    assert plan(client, subject=subj.pk, topics=ids, size=100, method="equal", seed=7).json()["rows"] == d["rows"]
    # qo'lda o'zgartirish: yig'indi saqlanadi, mavzu qulflanadi
    counts = {x["id"]: x["n"] for x in d["rows"]}
    d2 = plan(client, subject=subj.pk, topics=ids, size=100, method="equal", counts=counts, adjust={"id": ids[0], "n": 25}).json()
    row = {x["id"]: x for x in d2["rows"]}
    assert row[ids[0]]["n"] == 25 and row[ids[0]]["locked"] and sum(x["n"] for x in d2["rows"]) == 100
    # qulflangan mavzu son o'zgarganda ham o'z qiymatini saqlaydi
    counts2 = {x["id"]: x["n"] for x in d2["rows"]}
    d3 = plan(client, subject=subj.pk, topics=ids, size=60, method="proportional", counts=counts2, locks=[ids[0]]).json()
    assert {x["id"]: x for x in d3["rows"]}[ids[0]]["n"] == 25 and sum(x["n"] for x in d3["rows"]) == 60
    # son o'zgarib qulf sig'maydigan bo'lsa, qulflar bekor qilinadi
    d4 = plan(client, subject=subj.pk, topics=ids, size=20, method="equal", counts=counts2, locks=[ids[0]]).json()
    assert not any(x["locked"] for x in d4["rows"]) and sum(x["n"] for x in d4["rows"]) == 20 and d4["notes"]


def test_plan_endpoint_validation_and_isolation(client, teacher):
    subj, topics = make_subject(teacher, (30, 30))
    ids = [t.pk for t in topics]
    assert plan(client, subject=subj.pk, topics=ids, size=20).status_code == 302  # kirmagan
    client.login(username="ustoz", password="pw12345")
    assert plan(client, subject=subj.pk, topics=ids, size=10).status_code == 200
    assert plan(client, subject=subj.pk, topics=ids, size=100).status_code == 200
    for bad in (9, 101, "x", None):
        assert plan(client, subject=subj.pk, topics=ids, size=bad).status_code == 400
    assert plan(client, subject=subj.pk, topics=[], size=20).status_code == 400
    assert client.post(reverse("set_plan"), "[1]", content_type="application/json").status_code == 400
    assert client.post(reverse("set_plan"), "nojson", content_type="application/json").status_code == 400
    User.objects.create_user("b", password="x")
    client.login(username="b", password="x")
    assert plan(client, subject=subj.pk, topics=ids, size=20).status_code == 400  # boshqa o'qituvchining fani


