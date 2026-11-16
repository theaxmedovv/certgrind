"""PCEP: savollar tanlash, serverda baholash, natija hisoblash."""
import random

from django.db.models import Q
from django.utils import timezone

from .models import PcepAttempt, PcepAttemptAnswer, PcepModule, PcepQuestion

PASS_PERCENT = 70
# Imtihondagi 30 savol bo'yicha aralash test taqsimoti (1-4 modul)
MIXED_BASE = {1: 5, 2: 9, 3: 8, 4: 8}
EXAM_TOTAL = 30
EXAM_SECONDS = 40 * 60
SECONDS_PER_QUESTION = 80  # 30 savol = 40 daqiqa
SIZES = (10, 20, 30)


def mixed_distribution(total, base=None):
    """total ta savolni 5/9/8/8 nisbatida modullarga taqsimlaydi (eng katta qoldiq usuli).
    total=30 bo'lsa aynan 5/9/8/8 chiqadi."""
    base = base or MIXED_BASE
    s = sum(base.values())
    raw = {m: total * w / s for m, w in base.items()}
    out = {m: int(v) for m, v in raw.items()}
    rest = total - sum(out.values())
    for m in sorted(raw, key=lambda k: (raw[k] - out[k]), reverse=True)[:rest]:
        out[m] += 1
    return out


def attempts_for(request):
    """Joriy foydalanuvchi (yoki sessiya)ning tugatilgan urinishlari."""
    if request.user.is_authenticated:
        return PcepAttempt.objects.filter(user=request.user)
    ids = request.session.get("pcep_attempts", [])
    return PcepAttempt.objects.filter(id__in=ids, user__isnull=True)


def missed_counts(request):
    """question_id -> necha marta xato qilingan (kamroq takrorlash uchun og'irlik)."""
    ans = PcepAttemptAnswer.objects.filter(
        attempt__in=attempts_for(request).filter(finished_at__isnull=False), is_correct=False
    ).values_list("question_id", flat=True)
    cnt = {}
    for qid in ans:
        cnt[qid] = cnt.get(qid, 0) + 1
    return cnt


def weighted_sample(questions, k, missed):
    """Ko'p xato qilingan savollarga ustuvorlik berib, tasodifiy tanlaydi (takrorsiz)."""
    pool = list(questions)
    keyed = []
    for q in pool:
        w = 1 + 2 * missed.get(q.id, 0)
        keyed.append((random.random() ** (1.0 / w), q))
    keyed.sort(key=lambda t: t[0], reverse=True)
    return [q for _, q in keyed[:k]]


def pick_questions(kind, size, missed, module=None, only_ids=None):
    """kind: module | mixed | exam | practice | final | mistakes"""
    if kind == "mistakes":
        qs = list(PcepQuestion.objects.filter(id__in=only_ids or []))
        random.shuffle(qs)
        return qs
    if kind == "module":
        qs = PcepQuestion.objects.filter(bank="module", module=module)
        n = qs.count() if size in (None, 0) else min(size, qs.count())
        return weighted_sample(qs, n, missed)
    if kind in ("mixed", "exam"):
        total = EXAM_TOTAL if kind == "exam" else size
        dist = mixed_distribution(total)
        picked = []
        for num, cnt in dist.items():
            qs = PcepQuestion.objects.filter(bank="module", module__number=num)
            picked += weighted_sample(qs, cnt, missed)
        random.shuffle(picked)
        return picked
    # practice / final — to'plam tartibida emas, aralashtirilgan holda hammasi
    qs = list(PcepQuestion.objects.filter(bank=kind))
    random.shuffle(qs)
    return qs


def time_limit(attempt):
    if not attempt.timed:
        return 0
    if attempt.mode == "exam":
        return EXAM_SECONDS
    return attempt.total * SECONDS_PER_QUESTION


def create_attempt(request, kind, size=30, timed=False, module=None, only_ids=None):
    missed = missed_counts(request)
    questions = pick_questions(kind, size, missed, module=module, only_ids=only_ids)
    if not questions:
        return None
    if kind == "exam":
        timed = True
    attempt = PcepAttempt.objects.create(
        user=request.user if request.user.is_authenticated else None,
        mode=kind,
        module=module,
        total=len(questions),
        timed=bool(timed),
    )
    for i, q in enumerate(questions):
        if q.question_type in PcepQuestion.INTERACTIVE:
            opts = shuffle_ids(q)
        else:
            opts = list(q.options.values_list("id", flat=True))
            random.shuffle(opts)  # variantlar tartibi tasodifiy
        PcepAttemptAnswer.objects.create(attempt=attempt, question=q, order=i, option_order=opts)
    ids = request.session.get("pcep_attempts", [])
    request.session["pcep_attempts"] = ids + [attempt.id]
    return attempt


def can_access(request, attempt):
    if attempt.user_id:
        return request.user.is_authenticated and request.user.id == attempt.user_id
    return attempt.id in request.session.get("pcep_attempts", [])


def grade_answer(ans):
    q = ans.question
    if q.question_type in PcepQuestion.INTERACTIVE:
        return interactive_correct(q, ans.response or {})
    correct = set(ans.question.options.filter(is_correct=True).values_list("id", flat=True))
    chosen = set(ans.selected_option_ids or [])
    return bool(chosen) and chosen == correct


def finish_attempt(attempt):
    """Serverda baholaydi. Qayta chaqirilsa, natija o'zgarmaydi."""
    if attempt.finished_at:
        return attempt
    right = 0
    for a in attempt.answers.select_related("question"):
        a.is_correct = grade_answer(a)
        a.save(update_fields=["is_correct"])
        right += a.is_correct
    now = timezone.now()
    attempt.correct = right
    attempt.percent = percent(right, attempt.total)
    attempt.finished_at = now
    spent = int((now - attempt.started_at).total_seconds())
    limit = time_limit(attempt)
    attempt.duration_seconds = min(spent, limit) if limit else spent
    attempt.save()
    return attempt


def percent(correct, total):
    return round(100 * correct / total, 1) if total else 0.0


def passed(pct):
    return pct >= PASS_PERCENT


SECTION_NAMES = {
    "1.1": "Asosiy tushunchalar", "1.2": "Python mantig'i va izohlar", "1.3": "Literallar va o'zgaruvchilar",
    "1.4": "Operatorlar va ma'lumot turlari", "1.5": "Kiritish va chiqarish",
    "2.1": "Shartli operatorlar", "2.2": "Tsikllar",
    "3.1": "Ro'yxatlar", "3.2": "Tuple'lar", "3.3": "Lug'atlar", "3.4": "Satrlar",
    "4.1": "Funksiyalar", "4.2": "Argumentlar va ko'rinish doirasi", "4.3": "Exception'lar va rekursiya",
}


def module_breakdown(attempt):
    """Urinish bo'yicha modullar kesimi: [{number, title, right, total, pct}]"""
    rows = {}
    for a in attempt.answers.select_related("question__module"):
        m = a.question.module
        key = m.number if m else 0
        r = rows.setdefault(key, {"number": key, "title": m.title if m else "Boshqa", "right": 0, "total": 0})
        r["total"] += 1
        r["right"] += 1 if a.is_correct else 0
    out = []
    for k in sorted(rows):
        r = rows[k]
        r["pct"] = round(100 * r["right"] / r["total"])
        out.append(r)
    return out


def weakest_module(breakdown):
    cand = [r for r in breakdown if r["total"] >= 2 and r["number"]]
    return min(cand, key=lambda r: (r["pct"], -r["total"])) if cand else None


def section_stats(attempts_qs, limit=6):
    """Eng ko'p xato qilingan bo'limlar: [{section, name, wrong_pct, n}]"""
    agg = {}
    for sec, ok in PcepAttemptAnswer.objects.filter(
        attempt__in=attempts_qs.filter(finished_at__isnull=False)
    ).exclude(question__section="").values_list("question__section", "is_correct"):
        t = agg.setdefault(sec, [0, 0])
        t[0] += 1
        t[1] += 0 if ok else 1
    rows = [
        {"section": s, "name": SECTION_NAMES.get(s, ""), "n": n, "wrong_pct": round(100 * w / n)}
        for s, (n, w) in agg.items() if n >= 3 and w
    ]
    rows.sort(key=lambda r: (-r["wrong_pct"], -r["n"]))
    return rows[:limit]


def readiness(attempts_qs):
    """Oxirgi 3 ta aralash/imtihon testining o'rtacha foizi (None — yetarli ma'lumot yo'q)."""
    last = list(attempts_qs.filter(mode__in=["mixed", "exam"], finished_at__isnull=False).order_by("-finished_at")[:3])
    if not last:
        return None
    return {"pct": round(sum(a.percent for a in last) / len(last)), "n": len(last)}


# ---------------- interaktiv savollar ----------------
def block_ids(q):
    """Savoldagi tartiblanadigan/sudraladigan elementlar id'lari (tasodifiy tartib uchun)."""
    ix = q.interaction
    return [b["id"] for b in (ix.get("blocks") or ix.get("items") or [])]


def shuffle_ids(q):
    ids = block_ids(q)
    random.shuffle(ids)
    if q.question_type == PcepQuestion.ORDER and ids == q.interaction["answer"] and len(ids) > 1:
        ids.reverse()  # boshlang'ich holat to'g'ri javob bo'lib qolmasin
    return ids


def expected_slots(q):
    ix = q.interaction
    ans = ix["answer"]
    if q.question_type == PcepQuestion.CATEGORIZE:
        pre = ix.get("prefilled", {})
        return {k: v for k, v in ans.items() if k not in pre}
    return ans


def _answers_options(q):
    """Asosiy javob va alternativlar (code_gap)."""
    ix = q.interaction
    return [expected_slots(q)] + list(ix.get("alternatives") or [])


def interactive_correct(q, resp):
    t = q.question_type
    if t == PcepQuestion.ORDER:
        return resp.get("order") == q.interaction["answer"]
    slots = resp.get("slots") or {}
    if len(set(slots.values())) != len(slots.values()) and t in (PcepQuestion.MATCH, PcepQuestion.CODE_GAP):
        return False  # bitta blok ikki katakka qo'yilmaydi
    return any(slots == a for a in _answers_options(q))


def slot_report(q, resp):
    """{'ok': n, 'total': N, 'slots': {katak_id: True/False}} — qisman natija ko'rsatish uchun."""
    t = q.question_type
    if t == PcepQuestion.ORDER:
        ans, got = q.interaction["answer"], resp.get("order") or []
        flags = {str(i): (i < len(got) and got[i] == a) for i, a in enumerate(ans)}
        best = ans
    else:
        slots = resp.get("slots") or {}
        best = max(_answers_options(q), key=lambda a: sum(1 for k, v in a.items() if slots.get(k) == v))
        flags = {k: slots.get(k) == v for k, v in best.items()}
    return {"ok": sum(flags.values()), "total": len(flags), "slots": flags, "best": best}


def sanitize_response(q, raw):
    """Brauzerdan kelgan javobni tekshirib, toza ko'rinishga keltiradi (yoki None)."""
    ix, t = q.interaction, q.question_type
    if not isinstance(raw, dict):
        return None
    if t == PcepQuestion.ORDER:
        order = raw.get("order")
        ids = [i["id"] for i in ix["items"]]
        if isinstance(order, list) and sorted(map(str, order)) == sorted(ids):
            return {"order": [str(i) for i in order]}
        return {} if not order else None
    slots = raw.get("slots")
    if not isinstance(slots, dict):
        return None
    if t == PcepQuestion.MATCH:
        keys, vals = {x["id"] for x in ix["targets"]}, {x["id"] for x in ix["items"]}
    elif t == PcepQuestion.CODE_GAP:
        keys, vals = set(ix["answer"]), {x["id"] for x in ix["blocks"]}
    else:  # categorize
        pre = set(ix.get("prefilled", {}))
        keys, vals = {x["id"] for x in ix["items"]} - pre, {c["id"] for c in ix["categories"]}
    clean = {str(k): str(v) for k, v in slots.items() if str(k) in keys and str(v) in vals}
    if t != PcepQuestion.CATEGORIZE and len(set(clean.values())) != len(clean):
        return None
    return {"slots": clean}


def is_answered(q, resp):
    t = q.question_type
    if t == PcepQuestion.ORDER:
        return bool(resp.get("order"))
    n = len(resp.get("slots") or {})
    if t == PcepQuestion.MATCH:
        return n == len(q.interaction["targets"])
    return n == len(expected_slots(q))
