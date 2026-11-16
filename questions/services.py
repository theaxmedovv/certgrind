"""Excel (3 varaqli format) import va mavzu/fan yordamchilari."""
import re
from io import BytesIO

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from .models import Question, QuestionOption, QuestionSet, QuestionSetItem, Subject, Topic

LETTERS = "ABCDEF"
DIFF = {
    "oson": "easy", "easy": "easy", "1": "easy",
    "o'rta": "medium", "orta": "medium", "medium": "medium", "2": "medium",
    "qiyin": "hard", "hard": "hard", "3": "hard",
}
SHEET_Q, SHEET_S, SHEET_I = "Savollar", "To'plamlar", "To'plam savollari"


# ------------------------------------------------------------------ yordamchilar
def default_subject(teacher, name="Python"):
    subj, _ = Subject.objects.get_or_create(teacher=teacher, name=name)
    return subj


def get_topic(teacher, name, subject=None):
    """Mavzuni nomi bo'yicha topadi yoki yaratadi (oxiriga tartib raqami bilan)."""
    name = name.strip()[:120]
    qs = Topic.objects.filter(teacher=teacher, name=name)
    if subject is not None:
        qs = qs.filter(subject=subject)
    topic = qs.first()
    if topic:
        return topic
    subject = subject or default_subject(teacher)
    order = (Topic.objects.filter(subject=subject).order_by("-order").values_list("order", flat=True).first() or 0) + 1
    return Topic.objects.create(teacher=teacher, subject=subject, name=name, order=order)


def _norm(v):
    s = "" if v is None else str(v)
    for ch in "ʻʼ’‘`´":
        s = s.replace(ch, "'")
    return s.strip().lower()


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _int(v):
    m = re.search(r"\d+", _s(v))
    return int(m.group()) if m else None


def _find_cols(header):
    """Sarlavha qatoridan ustun indekslarini topadi (nomi bo'yicha, tartibga bog'liq emas)."""
    cols = {}
    for i, raw in enumerate(header):
        h = _norm(raw)
        if not h:
            continue
        if h in ("№", "no", "n", "savol №", "savol no", "savol n"):
            cols.setdefault("no", i)
        elif h.startswith("mavzu") and ("№" in h or h.endswith(" no") or h.endswith(" n")):
            cols["topic_no"] = i
        elif h.startswith("mavzu"):
            cols.setdefault("topic", i)
        elif h.startswith("savol"):
            cols.setdefault("text", i)
        elif h.startswith("kod"):
            cols["code"] = i
        elif h in tuple(l.lower() for l in LETTERS):
            cols[h.upper()] = i
        elif h.startswith("to'g'ri"):
            cols["answer"] = i
        elif h.startswith("qiyin"):
            cols["diff"] = i
        elif h.startswith("kiritilad"):
            cols["input"] = i
    return cols


def _sheet(wb, name):
    for ws in wb.worksheets:
        if _norm(ws.title) == _norm(name):
            return ws
    return None


def _rows(ws):
    it = ws.iter_rows(values_only=True)
    header = next(it, None)
    if header is None:
        return {}, []
    cols = _find_cols(header)
    return cols, [(i, r) for i, r in enumerate(it, start=2) if any(c not in (None, "") for c in r)]


def _get(row, cols, key):
    i = cols.get(key)
    return "" if i is None or i >= len(row) else _s(row[i])


# ------------------------------------------------------------------ import
def import_workbook(file, teacher, subject_name="Python", grade=""):
    """Excel faylni yuklaydi. Xatoli qatorlar o'tkazib yuboriladi, to'g'rilari saqlanadi.

    Qaytaradi: hisobot dict. Takroriy import mavjud mavzu/savol/to'plamni takrorlamaydi.
    """
    rep = {
        "file_error": None, "errors": [], "topics_created": 0, "questions_created": 0,
        "questions_existing": 0, "sets_created": 0, "sets_existing": 0, "subject": subject_name,
    }
    try:
        wb = load_workbook(file, read_only=False, data_only=True)
    except Exception:
        rep["file_error"] = "Fayl Excel (.xlsx) formatida emas"
        return rep
    ws_q = _sheet(wb, SHEET_Q)
    if ws_q is None:
        rep["file_error"] = f"'{SHEET_Q}' varag'i topilmadi"
        return rep

    def err(sheet, row, reason):
        rep["errors"].append({"sheet": sheet, "row": row, "reason": reason})

    cols, rows = _rows(ws_q)
    for need in ("text", "answer"):
        if need not in cols:
            rep["file_error"] = f"'{SHEET_Q}' varag'ida kerakli ustun topilmadi: {'Savol' if need == 'text' else 'To`g`ri javob'}"
            return rep
    if "A" not in cols or "B" not in cols:
        rep["file_error"] = f"'{SHEET_Q}' varag'ida A va B ustunlari kerak"
        return rep
    opt_letters = [l for l in LETTERS if l in cols]

    with transaction.atomic():
        subject, _ = Subject.objects.get_or_create(
            teacher=teacher, name=subject_name.strip()[:120] or "Python", defaults={"grade": grade}
        )
        topic_by_no, topic_by_name = {}, {}

        def topic_for(tno, tname):
            if tno is not None and tno in topic_by_no:
                return topic_by_no[tno]
            if tname and tname.lower() in topic_by_name and tno is None:
                return topic_by_name[tname.lower()]
            topic = None
            if tno is not None:
                topic = Topic.objects.filter(subject=subject, order=tno).first()
            if topic is None and tname:
                topic = Topic.objects.filter(subject=subject, name=tname[:120]).first()
            if topic is None:
                if not tname and tno is None:
                    return None
                order = tno if tno is not None else (
                    (Topic.objects.filter(subject=subject).order_by("-order").values_list("order", flat=True).first() or 0) + 1
                )
                topic = Topic.objects.create(
                    teacher=teacher, subject=subject, name=(tname or f"{tno}-mavzu")[:120], order=order
                )
                rep["topics_created"] += 1
            if tno is not None:
                topic_by_no[tno] = topic
            if tname:
                topic_by_name[tname.lower()] = topic
            return topic

        qmap = {}  # Excel № -> Question
        for rownum, row in rows:
            text = _get(row, cols, "text")
            if not text:
                err(SHEET_Q, rownum, "Savol matni bo'sh")
                continue
            tno, tname = _int(_get(row, cols, "topic_no")), _get(row, cols, "topic")
            if tno is None and not tname:
                err(SHEET_Q, rownum, "Mavzu ko'rsatilmagan")
                continue
            opts = [(l, _get(row, cols, l)) for l in opt_letters]
            opts = [(l, t) for l, t in opts if t]
            if len(opts) < 2:
                err(SHEET_Q, rownum, "Kamida 2 ta javob varianti kerak")
                continue
            ans = _get(row, cols, "answer").upper()
            if ans.isdigit() and 1 <= int(ans) <= len(LETTERS):
                ans = LETTERS[int(ans) - 1]
            if ans not in [l for l, _ in opts]:
                err(SHEET_Q, rownum, f"To'g'ri javob '{ans}' mavjud variantlardan biri emas")
                continue
            dtxt = _norm(_get(row, cols, "diff"))
            if dtxt and dtxt not in DIFF:
                err(SHEET_Q, rownum, f"Qiyinlik tanilmadi: '{dtxt}' (oson / o'rta / qiyin)")
                continue
            diff = DIFF.get(dtxt, "medium")
            topic = topic_for(tno, tname)
            ext = _int(_get(row, cols, "no"))
            q = None
            if ext is not None:
                q = Question.objects.filter(teacher=teacher, topic__subject=subject, external_no=ext).first()
            else:
                q = Question.objects.filter(teacher=teacher, topic=topic, text=text).first()
            if q:
                rep["questions_existing"] += 1
            else:
                q = Question.objects.create(
                    teacher=teacher, topic=topic, text=text, code=_get(row, cols, "code").rstrip(),
                    input_values=_get(row, cols, "input")[:300], difficulty=diff, external_no=ext,
                )
                QuestionOption.objects.bulk_create(
                    [QuestionOption(question=q, text=t[:500], is_correct=(l == ans)) for l, t in opts]
                )
                rep["questions_created"] += 1
            if ext is not None:
                qmap[ext] = q

        _import_sets(wb, teacher, subject, qmap, rep, err)
    return rep


def _import_sets(wb, teacher, subject, qmap, rep, err):
    ws_s, ws_i = _sheet(wb, SHEET_S), _sheet(wb, SHEET_I)
    if ws_s is None and ws_i is None:
        return
    sets = {}  # to'plam № -> dict(name, type, qnos)
    if ws_s is not None:
        header = next(ws_s.iter_rows(values_only=True), None) or []
        hn = [_norm(h) for h in header]
        def col(pred):
            return next((i for i, h in enumerate(hn) if pred(h)), None)
        c_no, c_name = col(lambda h: "to'plam" in h and ("№" in h or h.endswith("no"))), col(lambda h: h.startswith("nom"))
        c_type, c_qs = col(lambda h: h.startswith("turi")), col(lambda h: h.startswith("savollar"))
        for rownum, row in enumerate(ws_s.iter_rows(min_row=2, values_only=True), start=2):
            if not any(c not in (None, "") for c in row):
                continue
            no = _int(row[c_no]) if c_no is not None else None
            name = _s(row[c_name]) if c_name is not None else ""
            if no is None or not name:
                err(SHEET_S, rownum, "To'plam № yoki nomi yo'q")
                continue
            t = _norm(row[c_type]) if c_type is not None else ""
            stype = "cumulative" if "yig" in t else ("mixed" if "aralash" in t else "topic")
            qnos = [int(x) for x in re.findall(r"\d+", _s(row[c_qs]))] if c_qs is not None and c_qs < len(row) else []
            sets[no] = {"name": name, "type": stype, "qnos": qnos, "row": rownum}
    if ws_i is not None:
        header = next(ws_i.iter_rows(values_only=True), None) or []
        hn = [_norm(h) for h in header]
        c_set = next((i for i, h in enumerate(hn) if "to'plam" in h and ("№" in h or h.endswith("no"))), 0)
        c_name = next((i for i, h in enumerate(hn) if "nom" in h), None)
        c_ord = next((i for i, h in enumerate(hn) if h.startswith("tartib")), None)
        c_q = next((i for i, h in enumerate(hn) if h.startswith("savol")), None)
        if c_q is None:
            err(SHEET_I, 1, "'Savol №' ustuni topilmadi")
        else:
            items = {}
            for rownum, row in enumerate(ws_i.iter_rows(min_row=2, values_only=True), start=2):
                if not any(c not in (None, "") for c in row):
                    continue
                sno, qno = _int(row[c_set]), _int(row[c_q])
                if sno is None or qno is None:
                    err(SHEET_I, rownum, "To'plam № yoki Savol № yo'q")
                    continue
                order = _int(row[c_ord]) if c_ord is not None else None
                items.setdefault(sno, []).append((order if order is not None else 10**6, rownum, qno))
                if sno not in sets:
                    nm = _s(row[c_name]) if c_name is not None else ""
                    sets[sno] = {"name": nm or f"To'plam {sno}", "type": "mixed", "qnos": [], "row": rownum}
            for sno, lst in items.items():
                lst.sort()
                sets[sno]["qnos"] = [q for _, _, q in lst]
                sets[sno]["rows"] = {q: r for _, r, q in lst}

    for sno in sorted(sets):
        info = sets[sno]
        if QuestionSet.objects.filter(teacher=teacher, subject=subject, external_no=sno).exists():
            rep["sets_existing"] += 1
            continue
        questions, seen = [], set()
        for qno in info["qnos"]:
            q = qmap.get(qno) or Question.objects.filter(
                teacher=teacher, topic__subject=subject, external_no=qno
            ).first()
            if q is None:
                err(SHEET_I, info.get("rows", {}).get(qno, info["row"]), f"To'plam {sno}: Savol № {qno} topilmadi")
            elif q.pk not in seen:
                seen.add(q.pk)
                questions.append(q)
        if not questions:
            err(SHEET_S, info["row"], f"To'plam {sno} ('{info['name']}') savolsiz — o'tkazib yuborildi")
            continue
        qset = QuestionSet.objects.create(
            teacher=teacher, subject=subject, name=info["name"][:200], set_type=info["type"],
            size=len(questions), external_no=sno,
        )
        QuestionSetItem.objects.bulk_create(
            [QuestionSetItem(question_set=qset, question=q, order=i) for i, q in enumerate(questions, 1)]
        )
        qset.topics.set({q.topic for q in questions})
        rep["sets_created"] += 1


# ------------------------------------------------------------------ eksport / shablon
def _bold(ws):
    for c in ws[1]:
        c.font = Font(bold=True)


def build_template():
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_Q
    ws.append(["№", "Mavzu №", "Mavzu", "Savol", "Kod", "A", "B", "C", "D", "To'g'ri javob (A–D)",
               "Qiyinlik (oson/o'rta/qiyin)", "Kiritiladigan qiymatlar (input)"])
    ws.append([1, 1, "O'zgaruvchilar", "Kod natijasi nima?", "x = 2\nprint(x + 3)", "3", "5", "23", "", "B", "oson", ""])
    ws.append([2, 2, "Sikllar", "Qaysi sikl operatori?", "", "for", "if", "def", "", "A", "o'rta", ""])
    _bold(ws)
    s = wb.create_sheet(SHEET_S)
    s.append(["To'plam №", "Nomi", "Turi (📘 Mavzu / 📚 Yig'ma / 🎲 Aralash)", "Mavzular", "Hajmi", "oson", "o'rta", "qiyin", "Savollar №"])
    s.append([1, "1–2-mavzular", "📚 Yig'ma", "1, 2", 2, 1, 1, 0, "1, 2"])
    _bold(s)
    i = wb.create_sheet(SHEET_I)
    i.append(["To'plam №", "To'plam nomi", "Tartib", "Savol №", "Mavzu №", "Qiyinlik"])
    i.append([1, "1–2-mavzular", 1, 1, 1, "oson"])
    i.append([1, "1–2-mavzular", 2, 2, 2, "o'rta"])
    _bold(i)
    ws.column_dimensions["D"].width = 50
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_subject(subject, sets=None):
    """Fanning savollari va to'plamlarini import formatida chiqaradi."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_Q
    ws.append(["№", "Mavzu №", "Mavzu", "Savol", "Kod", "A", "B", "C", "D", "To'g'ri javob (A–D)",
               "Qiyinlik (oson/o'rta/qiyin)", "Kiritiladigan qiymatlar (input)"])
    inv = {v: k for k, v in {"oson": "easy", "o'rta": "medium", "qiyin": "hard"}.items()}
    if sets is not None:
        qs = Question.objects.filter(set_items__question_set__in=sets).distinct().select_related("topic")
    else:
        qs = Question.objects.filter(topic__subject=subject).select_related("topic").prefetch_related("options").order_by("topic__order", "id")
    nos = {}
    for n, q in enumerate(qs, 1):
        nos[q.pk] = q.external_no or n
        opts = list(q.options.all())[:4]
        texts = [o.text for o in opts] + [""] * (4 - len(opts))
        ans = next((LETTERS[i] for i, o in enumerate(opts) if o.is_correct), "")
        ws.append([nos[q.pk], q.topic.order, q.topic.name, q.text, q.code, *texts, ans, inv.get(q.difficulty, ""), q.input_values])
    _bold(ws)
    s = wb.create_sheet(SHEET_S)
    s.append(["To'plam №", "Nomi", "Turi", "Mavzular", "Hajmi", "oson", "o'rta", "qiyin", "Savollar №"])
    i = wb.create_sheet(SHEET_I)
    i.append(["To'plam №", "To'plam nomi", "Tartib", "Savol №", "Mavzu №", "Qiyinlik"])
    label = {"topic": "📘 Mavzu", "cumulative": "📚 Yig'ma", "mixed": "🎲 Aralash"}
    for n, qset in enumerate(sets if sets is not None else QuestionSet.objects.filter(subject=subject).order_by("id"), 1):
        items = list(qset.items.select_related("question__topic"))
        cnt = {"easy": 0, "medium": 0, "hard": 0}
        for it in items:
            cnt[it.question.difficulty] += 1
        s.append([n, qset.name, label[qset.set_type], ", ".join(str(t.order) for t in qset.topics.order_by("order")),
                  len(items), cnt["easy"], cnt["medium"], cnt["hard"], ", ".join(str(nos.get(it.question_id, "")) for it in items)])
        for it in items:
            i.append([n, qset.name, it.order, nos.get(it.question_id, ""), it.question.topic.order, inv.get(it.question.difficulty, "")])
    _bold(s)
    _bold(i)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
