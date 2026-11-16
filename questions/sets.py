"""To'plam generatori: tasodifiy, takrorsiz tanlash; taqsimot va qiyinlik aralashmasi."""
import random
from collections import Counter

from django.db import transaction
from django.db.models import Count

from .models import Question, QuestionSet, QuestionSetItem, Topic

_rng = random.SystemRandom()

SIZES = tuple(range(10, 101, 10))
MIN_SIZE, MAX_SIZE = 10, 100
SECONDS_PER_QUESTION = 30  # xona vaqti tavsiyasi uchun
# Yig'ma zinapoya: (nechta mavzugacha, hajm); None = barcha mavzular
LADDER = [(2, 10), (3, 15), (4, 20), (5, 25), (6, 30), (8, 40), (10, 50), (12, 60), (15, 60), (None, 100)]
DIFFS = ("easy", "medium", "hard")


def split(total, weights, rng=None):
    """total'ni weights nisbatida butun sonlarga bo'ladi (eng katta qoldiq usuli).

    rng berilsa, teng qoldiqlar orasida tasodifiy tanlanadi (masalan 100/7: qaysi 2 mavzu 15 oladi).
    """
    s = sum(weights)
    if total <= 0 or s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    out = [int(x) for x in raw]
    tie = [rng.random() if rng else 0 for _ in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - out[i]), tie[i]))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def fill_capped(total, weights, caps, rng=None):
    """total'ni weights nisbatida bo'ladi, lekin har biri caps'dan oshmaydi: oshgan qism qolganlarga
    o'tadi. Yig'indi aynan min(total, sum(caps))."""
    out = [0] * len(weights)
    remaining = min(total, sum(caps))
    active = [i for i in range(len(weights)) if caps[i] > 0]
    while remaining > 0 and active:
        w = [max(0, weights[i]) for i in active]
        if sum(w) <= 0:
            w = [1] * len(active)
        parts = split(remaining, w, rng)
        over = [i for i, p in zip(active, parts) if p > caps[i]]
        if not over:
            for i, p in zip(active, parts):
                out[i] = p
            break
        for i in over:
            out[i] = caps[i]
            remaining -= caps[i]
        active = [i for i in active if i not in over]
    return out


def normalize_mix(mix):
    vals = [max(0.0, float((mix or {}).get(k, 0) or 0)) for k in DIFFS]
    if sum(vals) <= 0:
        vals = [30, 50, 20]
    t = sum(vals)
    return {k: round(v * 100 / t) for k, v in zip(DIFFS, vals)}


def _spread(free, need, cap, method, last_id, n_topics, rng):
    """Qulflanmagan mavzular (free) orasida need ta savolni taqsimlaydi. {id: n}."""
    if method == QuestionSet.Distribution.RANDOM:
        pool = [i for i in free for _ in range(cap[i])]
        picks = Counter(rng.sample(pool, need))
        return {i: picks.get(i, 0) for i in free}
    eligible = [i for i in free if cap[i] > 0]
    if need < len(eligible):  # mavzular savollardan ko'p: mavzular tasodifiy tanlanadi
        return {i: 1 for i in rng.sample(eligible, need)}
    if method == QuestionSet.Distribution.PROPORTIONAL:
        weights = [cap[i] for i in eligible]
    elif method == QuestionSet.Distribution.LATEST_FOCUS and n_topics > 1 and last_id in eligible:
        weights = [40 if i == last_id else 60 / (n_topics - 1) for i in eligible]
    else:
        weights = [1] * len(eligible)
    out = fill_capped(need, weights, [cap[i] for i in eligible], rng)
    # hech bir mavzu 0 ta olmasligi kerak: eng ko'p olgan mavzudan bittadan olinadi
    for j in range(len(out)):
        if out[j] == 0:
            donor = max(range(len(out)), key=lambda k: out[k])
            if out[donor] <= 1:
                break
            out[donor] -= 1
            out[j] = 1
    return dict(zip(eligible, out))


def allocate(avail, total, method="equal", locks=None, rng=None):
    """Har bir mavzuga nechta savol tushishini hisoblaydi.

    avail: [(mavzu_id, bazadagi savollar)] — mavzular tartibida.
    locks: {mavzu_id: son} — qo'lda belgilangan (qulflangan) mavzular, ular o'zgarmaydi.
    Jami har doim aynan min(total, bazadagi jami) ga teng. Qaytaradi {"counts", "locks_dropped"}.
    """
    rng = rng or _rng
    ids = [i for i, _ in avail]
    cap = dict(avail)
    total = max(0, min(int(total), sum(cap.values())))
    locks = {i: min(max(0, int(n)), cap[i]) for i, n in (locks or {}).items() if i in cap}
    free = [i for i in ids if i not in locks]
    need = total - sum(locks.values())
    dropped = False
    if locks and (need < 0 or need > sum(cap[i] for i in free)):
        locks, free, need, dropped = {}, ids, total, True  # qulflar bilan jami chiqmaydi — bekor qilinadi
    counts = {**locks, **{i: 0 for i in free}}
    if need > 0 and free:
        counts.update(_spread(free, need, cap, method, ids[-1] if ids else None, len(ids), rng))
    return {"counts": counts, "locks_dropped": dropped}


def adjust_counts(avail, counts, locks, topic_id, new_n):
    """Bitta mavzuni qo'lda o'zgartiradi; yig'indi saqlanishi uchun farq qulflanmagan boshqa mavzulardan
    olinadi yoki shularga qo'shiladi. Qaytaradi (counts, locks) — o'zgargan mavzu qulflanadi."""
    total, k = sum(counts.values()), len(avail)
    lo = {i: (1 if total >= k and avail[i] > 0 else 0) for i in avail}
    others = [i for i in avail if i != topic_id and i not in locks]
    new_n = min(avail[topic_id], max(lo[topic_id], int(new_n)))
    delta = new_n - counts[topic_id]
    out = dict(counts)
    if delta > 0:
        take = fill_capped(delta, [counts[i] for i in others], [counts[i] - lo[i] for i in others])
        for i, t in zip(others, take):
            out[i] -= t
        new_n = counts[topic_id] + sum(take)
    elif delta < 0:
        give = fill_capped(-delta, [max(counts[i], 1) for i in others], [avail[i] - counts[i] for i in others])
        for i, g in zip(others, give):
            out[i] += g
        new_n = counts[topic_id] - sum(give)
    out[topic_id] = new_n
    return out, set(locks) | {topic_id}


def difficulty_plan(n, by_diff, mix):
    """Mavzudan n ta savol: qiyinlik bo'yicha nechtadan (yetmasa boshqa qiyinlikdan to'ldiriladi)."""
    mix = normalize_mix(mix)
    weights = [mix[k] for k in DIFFS]
    caps = [by_diff.get(k, 0) for k in DIFFS]
    n = min(n, sum(caps))
    first = [min(t, c) for t, c in zip(split(n, weights), caps)]
    extra = fill_capped(n - sum(first), weights, [c - f for c, f in zip(caps, first)])
    return {k: f + e for k, f, e in zip(DIFFS, first, extra)}


def topic_difficulty_counts(topics):
    """{mavzu_id: {easy, medium, hard}} — bazadagi savollar soni."""
    out = {t.pk: dict.fromkeys(DIFFS, 0) for t in topics}
    rows = Question.objects.filter(topic__in=topics).values("topic_id", "difficulty").annotate(n=Count("id"))
    for r in rows:
        out[r["topic_id"]][r["difficulty"]] = r["n"]
    return out


def build_plan(topics, size, method="equal", mix=None, counts=None, locks=(), adjust=None, seed=None):
    """Generator sahifasi uchun jonli taqsimot: har bir mavzu qatori + qiyinlik bo'yicha jadval.

    counts/locks — sahifadagi joriy holat (qulflangan mavzular o'z sonini saqlaydi);
    adjust={"id", "n"} — bitta mavzuni qo'lda o'zgartirish.
    """
    topics = sorted(topics, key=lambda t: (t.order, t.pk))
    rng = random.Random(seed) if seed is not None else _rng
    by_topic = topic_difficulty_counts(topics)
    avail = {t.pk: sum(by_topic[t.pk].values()) for t in topics}
    total_avail = sum(avail.values())
    effective = min(size, total_avail)
    counts = {i: n for i, n in (counts or {}).items() if i in avail}
    lock_ids = {i for i in locks if i in counts}
    notes = []
    current_ok = set(counts) == set(avail) and sum(counts.values()) == effective and all(
        0 <= counts[i] <= avail[i] for i in counts)
    if adjust and adjust.get("id") in avail and current_ok:
        res, lock_ids = adjust_counts(avail, counts, lock_ids, adjust["id"], adjust.get("n", 0))
    else:
        res = allocate([(t.pk, avail[t.pk]) for t in topics], size, method,
                       {i: counts[i] for i in lock_ids}, rng)
        if res["locks_dropped"]:
            lock_ids = set()
            notes.append("Son yoki mavzular o'zgargani uchun qulflar bekor qilindi")
        res = res["counts"]
    rows = []
    for t in topics:
        n = res.get(t.pk, 0)
        rows.append({"id": t.pk, "name": t.name, "order": t.order, "avail": avail[t.pk], "n": n,
                     "locked": t.pk in lock_ids, **difficulty_plan(n, by_topic[t.pk], mix)})
    return {
        "rows": rows, "effective": effective, "total_avail": total_avail, "notes": notes,
        "totals": {k: sum(r[k] for r in rows) for k in DIFFS},
    }


def valid_counts(counts, avail, size):
    """Sahifadan kelgan taqsimot to'g'rimi? To'g'ri bo'lsa {id: n}, aks holda None."""
    try:
        counts = {int(k): int(v) for k, v in dict(counts).items()}
    except (TypeError, ValueError):
        return None
    if set(counts) != set(avail) or any(not 0 <= n <= avail[i] for i, n in counts.items()):
        return None
    return counts if sum(counts.values()) == min(size, sum(avail.values())) else None


def pick_from_topic(topic, quota, mix, exclude_ids=()):
    """Mavzudan quota ta savol: qiyinlik aralashmasiga mos, yetmasa boshqa qiyinlikdan to'ldiradi."""
    pools = {k: [] for k in DIFFS}
    for q in Question.objects.filter(topic=topic).exclude(pk__in=exclude_ids):
        pools[q.difficulty].append(q)
    for p in pools.values():
        _rng.shuffle(p)
    plan = difficulty_plan(quota, {k: len(p) for k, p in pools.items()}, mix)
    picked = [q for k in DIFFS for q in pools[k][: plan[k]]]
    return picked, max(0, quota - len(picked))


def generate(topics, size, distribution="equal", mix=None, counts=None):
    """Tanlangan mavzulardan size ta savol. Qaytaradi (savollar, yetishmagani).

    counts — {mavzu_id: son}: o'qituvchi sahifada ko'rgan/sozlagan taqsimot (to'g'ri bo'lsa shu ishlatiladi).
    Mavzuda savol yetmasa ortgan qism boshqa mavzularga o'tadi; yetishmagani faqat bazada savol
    umuman kam bo'lganda bo'ladi.
    """
    topics = sorted(topics, key=lambda t: (t.order, t.pk))
    size = max(1, int(size))
    avail = {i: sum(d.values()) for i, d in topic_difficulty_counts(topics).items()}
    quota = valid_counts(counts, avail, size) if counts else None
    if quota is None:
        quota = allocate([(t.pk, avail[t.pk]) for t in topics], size, distribution)["counts"]
    picked = []
    for topic in topics:
        got, _ = pick_from_topic(topic, quota.get(topic.pk, 0), mix)
        picked += got
    picked.sort(key=lambda q: (q.topic.order, q.topic_id, q.pk))
    return picked, max(0, size - len(picked))


def suggest_name(set_type, topics, count):
    topics = sorted(topics, key=lambda t: (t.order, t.pk))
    if not topics:
        return f"To'plam ({count} ta)"
    if set_type == QuestionSet.Type.TOPIC:
        return f"{topics[0].name} ({count} ta)"
    if set_type == QuestionSet.Type.CUMULATIVE:
        return f"{topics[0].order}–{topics[-1].order}-mavzular ({count} ta)"
    names = ", ".join(t.name for t in topics[:3]) + ("…" if len(topics) > 3 else "")
    return f"Aralash: {names} ({count} ta)"


@transaction.atomic
def save_set(teacher, subject, name, set_type, topics, size, distribution, mix, questions, instance=None,
             allocation=None):
    if instance is None:
        instance = QuestionSet(teacher=teacher, subject=subject)
    instance.name = name[:200]
    instance.set_type = set_type
    instance.size = size
    instance.distribution = distribution
    instance.difficulty_mix = normalize_mix(mix)
    # mavzular bo'yicha taqsimot: qayta aralashtirganda shu saqlanadi ("to'liq tasodifiy"da saqlanmaydi)
    if allocation is None and distribution != QuestionSet.Distribution.RANDOM:
        allocation = dict(Counter(str(q.topic_id) for q in questions))
    instance.allocation = allocation
    instance.save()
    instance.topics.set(topics)
    instance.items.all().delete()
    QuestionSetItem.objects.bulk_create(
        [QuestionSetItem(question_set=instance, question=q, order=i) for i, q in enumerate(questions, 1)]
    )
    return instance


def set_stats(qset):
    """Diagramma uchun: mavzular va qiyinlik bo'yicha taqsimot."""
    items = list(qset.items.select_related("question__topic"))
    per_topic, diff = {}, {"easy": 0, "medium": 0, "hard": 0}
    for it in items:
        t = it.question.topic
        per_topic.setdefault(t.pk, {"name": t.name, "order": t.order, "n": 0})["n"] += 1
        diff[it.question.difficulty] += 1
    topics = sorted(per_topic.values(), key=lambda x: x["order"])
    total = len(items) or 1
    for t in topics:
        t["pct"] = round(t["n"] * 100 / total)
    return {
        "items": items, "topics": topics, "diff": diff, "count": len(items),
        "diff_pct": {k: round(v * 100 / total) for k, v in diff.items()},
        "missing": max(0, qset.size - len(items)),
    }


def replacement_for(qset, item):
    """Shu mavzudan to'plamda yo'q boshqa savol (tasodifiy)."""
    used = set(qset.items.values_list("question_id", flat=True))
    cands = list(Question.objects.filter(topic=item.question.topic).exclude(pk__in=used))
    # avvalo bir xil qiyinlik
    same = [q for q in cands if q.difficulty == item.question.difficulty]
    pool = same or cands
    return _rng.choice(pool) if pool else None


def auto_create_all(teacher, subject):
    """Har mavzuga 1 ta mavzu to'plami (15) + yig'ma zinapoya; mavjudlari takrorlanmaydi."""
    topics = list(subject.topics.order_by("order", "id"))
    created, skipped, notes = 0, 0, []
    made = set()

    def exists(set_type, tset, size):
        for s in QuestionSet.objects.filter(teacher=teacher, subject=subject, set_type=set_type, size=size):
            if set(s.topics.values_list("pk", flat=True)) == tset:
                return True
        return False

    def make(set_type, tps, size, distribution, note=True):
        nonlocal created, skipped
        avail = Question.objects.filter(topic__in=tps).count()
        real = min(size, avail)
        if real < 1:
            notes.append(f"{suggest_name(set_type, tps, size)} — savol yo'q")
            return
        key = (set_type, frozenset(t.pk for t in tps), real)
        if key in made:  # savol kamligidan zinapoyaning ikki pog'onasi bir xil to'plam bo'lib qoldi
            return
        made.add(key)
        if exists(set_type, {t.pk for t in tps}, real):
            skipped += 1
            return
        qs, _ = generate(tps, real, distribution)
        save_set(teacher, subject, suggest_name(set_type, tps, len(qs)), set_type, tps, len(qs),
                 distribution, None, qs)
        created += 1
        if real < size and note:
            notes.append(f"{suggest_name(set_type, tps, len(qs))}: savol yetmadi ({real}/{size})")

    for t in topics:
        make(QuestionSet.Type.TOPIC, [t], 15, "equal")
    for n, size in LADDER:
        upto = topics if n is None else topics[:n]
        if len(upto) < 2 or (n is not None and len(topics) < n):
            continue
        make(QuestionSet.Type.CUMULATIVE, upto, size, "equal", note=n is not None)
    return {"created": created, "skipped": skipped, "notes": notes}
