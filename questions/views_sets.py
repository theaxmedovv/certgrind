import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services, sets
from .models import QuestionSet, QuestionSetItem, Subject, Topic


def _own_set(request, pk):
    return get_object_or_404(QuestionSet, pk=pk, teacher=request.user)


@login_required
def set_list(request):
    """To'plamlar kutubxonasi: filtr (fan, tur, hajm, mavzu), kartalar."""
    qs = QuestionSet.objects.filter(teacher=request.user).select_related("subject").prefetch_related("topics")
    f = {k: request.GET.get(k, "") for k in ("subject", "type", "size", "topic")}
    if f["subject"]:
        qs = qs.filter(subject_id=f["subject"])
    if f["type"]:
        qs = qs.filter(set_type=f["type"])
    if f["size"].isdigit():
        qs = qs.filter(size=int(f["size"]))
    if f["topic"]:
        qs = qs.filter(topics__pk=f["topic"])
    cards = []
    for s in qs.distinct():
        st = sets.set_stats(s)
        cards.append({"set": s, "stats": st, "topics": sorted(s.topics.all(), key=lambda t: t.order)})
    return render(
        request,
        "teacher/set_list.html",
        {
            "cards": cards, "f": f,
            "subjects": Subject.objects.filter(teacher=request.user),
            "topics": Topic.objects.filter(teacher=request.user).select_related("subject"),
            "types": QuestionSet.Type.choices,
            "sizes": sorted(set(QuestionSet.objects.filter(teacher=request.user).values_list("size", flat=True))),
        },
    )


def _read_form(request, subject):
    """Generator formasidan sozlamalarni o'qiydi. Qaytaradi (data, xatolar)."""
    P = request.POST
    errors = []
    set_type = P.get("set_type", "topic")
    if set_type not in QuestionSet.Type.values:
        set_type = "topic"
    all_topics = list(subject.topics.order_by("order", "id"))
    if set_type == "topic":
        chosen = [t for t in all_topics if str(t.pk) == P.get("topic")]
    elif set_type == "cumulative":
        try:
            upto = int(P.get("upto", "0"))
        except ValueError:
            upto = 0
        chosen = all_topics[: max(0, upto)]
        if len(chosen) < 2:
            errors.append("Yig'ma to'plam uchun kamida 2 ta mavzu kerak")
    else:
        ids = set(P.getlist("topics"))
        chosen = [t for t in all_topics if str(t.pk) in ids]
    if not chosen:
        errors.append("Mavzuni tanlang")
    try:
        size = int(P.get("size", "15"))
    except ValueError:
        size = 15
    if not sets.MIN_SIZE <= size <= sets.MAX_SIZE:
        errors.append(f"Hajm {sets.MIN_SIZE} dan {sets.MAX_SIZE} gacha bo'lishi kerak")
        size = min(max(size, sets.MIN_SIZE), sets.MAX_SIZE)
    dist = P.get("distribution", "equal")
    if dist not in QuestionSet.Distribution.values:
        dist = "equal"

    def num(k, d):
        try:
            return float(P.get(k, d))
        except ValueError:
            return d

    mix = sets.normalize_mix({"easy": num("mix_easy", 30), "medium": num("mix_medium", 50), "hard": num("mix_hard", 20)})
    try:  # sahifada ko'rsatilgan/sozlangan taqsimot: {mavzu_id: son}
        alloc = json.loads(P.get("alloc") or "null")
        alloc = alloc if isinstance(alloc, dict) else None
    except ValueError:
        alloc = None
    return {"set_type": set_type, "topics": chosen, "size": size, "distribution": dist, "mix": mix, "alloc": alloc}, errors


@login_required
def set_generate(request):
    subjects = list(Subject.objects.filter(teacher=request.user))
    subject = None
    sid = request.POST.get("subject") or request.GET.get("subject")
    if sid:
        subject = next((s for s in subjects if str(s.pk) == sid), None)
    subject = subject or (subjects[0] if subjects else None)
    errors = []
    if request.method == "POST" and subject:
        data, errors = _read_form(request, subject)
        if not errors:
            qs, short = sets.generate(data["topics"], data["size"], data["distribution"], data["mix"], counts=data["alloc"])
            if not qs:
                errors.append("Tanlangan mavzularda savol yo'q")
            else:
                name = request.POST.get("name", "").strip() or sets.suggest_name(data["set_type"], data["topics"], len(qs))
                qset = sets.save_set(request.user, subject, name, data["set_type"], data["topics"],
                                     data["size"], data["distribution"], data["mix"], qs)
                if request.headers.get("x-requested-with") == "fetch":
                    return JsonResponse({
                        "ok": True, "id": qset.pk, "name": qset.name, "type": qset.set_type,
                        "type_label": qset.get_set_type_display(), "count": qset.items.count(),
                        "subject": subject.pk, "short": short,
                        "topics": [t.name for t in sorted(data["topics"], key=lambda t: t.order)][:4],
                    })
                if short:
                    messages.warning(request, f"So'ralgan {data['size']} tadan {short} tasi yetmadi — tanlangan mavzularda savol kam")
                return redirect("set_detail", pk=qset.pk)
    if errors and request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    tdata = {}
    for s in subjects:
        tdata[s.pk] = [
            {"id": t.pk, "name": t.name, "order": t.order, "n": t.n}
            for t in s.topics.annotate(n=Count("questions")).order_by("order", "id")
        ]
    return render(
        request, "teacher/set_generate.html",
        {"subjects": subjects, "subject": subject, "topics_json": tdata, "errors": errors,
         "sizes": sets.SIZES, "dists": QuestionSet.Distribution.choices, "post": request.POST,
         "plan_url": reverse("set_plan"), "min_size": sets.MIN_SIZE, "max_size": sets.MAX_SIZE},
    )


@login_required
def set_detail(request, pk):
    qset = _own_set(request, pk)
    st = sets.set_stats(qset)
    return render(request, "teacher/set_detail.html", {"qset": qset, "st": st, "topics": sorted(qset.topics.all(), key=lambda t: t.order),
                                                        "mix": qset.difficulty_mix})


@login_required
@require_POST
def set_rename(request, pk):
    qset = _own_set(request, pk)
    name = request.POST.get("name", "").strip()
    if name:
        qset.name = name[:200]
        qset.save(update_fields=["name"])
    return redirect("set_detail", pk=pk)


@login_required
@require_POST
def set_reshuffle(request, pk):
    """Shu sozlamalar bilan boshqa tasodifiy savollar."""
    qset = _own_set(request, pk)
    qs, short = sets.generate(list(qset.topics.all()), qset.size, qset.distribution, qset.difficulty_mix,
                              counts=qset.allocation)
    if qs:
        sets.save_set(request.user, qset.subject, qset.name, qset.set_type, list(qset.topics.all()),
                      qset.size, qset.distribution, qset.difficulty_mix, qs, instance=qset,
                      allocation=qset.allocation)
        messages.success(request, "Savollar qayta aralashtirildi")
    return redirect("set_detail", pk=pk)


@login_required
@require_POST
def set_item_replace(request, pk, item_pk):
    qset = _own_set(request, pk)
    item = get_object_or_404(QuestionSetItem, pk=item_pk, question_set=qset)
    new_q = sets.replacement_for(qset, item)
    if new_q is None:
        messages.warning(request, "Shu mavzudan almashtirish uchun boshqa savol yo'q")
    else:
        item.question = new_q
        item.save(update_fields=["question"])
    return redirect("set_detail", pk=pk)


@login_required
@require_POST
def set_item_remove(request, pk, item_pk):
    qset = _own_set(request, pk)
    get_object_or_404(QuestionSetItem, pk=item_pk, question_set=qset).delete()
    for n, it in enumerate(qset.items.order_by("order", "id"), 1):
        if it.order != n:
            QuestionSetItem.objects.filter(pk=it.pk).update(order=n)
    return redirect("set_detail", pk=pk)


@login_required
@require_POST
def set_copy(request, pk):
    src = _own_set(request, pk)
    new = sets.save_set(
        request.user, src.subject, f"{src.name} (nusxa)", src.set_type, list(src.topics.all()),
        src.size, src.distribution, src.difficulty_mix, [it.question for it in src.items.select_related("question__topic")],
        allocation=src.allocation,
    )
    messages.success(request, "Nusxa yaratildi")
    return redirect("set_detail", pk=new.pk)


@login_required
@require_POST
def set_delete(request, pk):
    _own_set(request, pk).delete()
    messages.success(request, "To'plam o'chirildi")
    return redirect("set_list")


@login_required
def set_export(request, pk):
    qset = _own_set(request, pk)
    resp = HttpResponse(
        services.export_subject(qset.subject, sets=[qset]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="toplam_{qset.pk}.xlsx"'
    return resp


@login_required
@require_POST
def set_auto_all(request):
    subject = get_object_or_404(Subject, pk=request.POST.get("subject"), teacher=request.user)
    res = sets.auto_create_all(request.user, subject)
    messages.success(request, f"{res['created']} ta to'plam yaratildi, {res['skipped']} tasi avvaldan bor edi")
    for n in res["notes"][:5]:
        messages.warning(request, n)
    return redirect("set_list")


def _ints(values):
    out = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    return out


@login_required
@require_POST
def set_plan(request):
    """Generator sahifasi uchun jonli taqsimot (JSON): mavzular, son, usul, qulflar, qo'lda o'zgartirish."""
    def bad(msg):
        return JsonResponse({"ok": False, "errors": [msg]}, status=400)

    try:
        P = json.loads(request.body or b"{}")
        size = int(P.get("size"))
        subject = Subject.objects.filter(pk=int(P.get("subject")), teacher=request.user).first()
    except (ValueError, TypeError, AttributeError):
        return bad("Noto'g'ri so'rov")
    if subject is None:
        return bad("Fan topilmadi")
    if not sets.MIN_SIZE <= size <= sets.MAX_SIZE:
        return bad(f"Hajm {sets.MIN_SIZE} dan {sets.MAX_SIZE} gacha bo'lishi kerak")
    topics = list(subject.topics.filter(pk__in=_ints(P.get("topics"))))
    if not topics:
        return bad("Mavzuni tanlang")
    method = P.get("method") if P.get("method") in QuestionSet.Distribution.values else "equal"
    counts = {}
    for k, v in (P.get("counts") or {}).items():
        try:
            counts[int(k)] = int(v)
        except (TypeError, ValueError):
            pass
    adjust = None
    if isinstance(P.get("adjust"), dict):
        ids, ns = _ints([P["adjust"].get("id")]), _ints([P["adjust"].get("n")])
        adjust = {"id": ids[0], "n": ns[0]} if ids and ns else None
    mix = P.get("mix") if isinstance(P.get("mix"), dict) else None
    seed = _ints([P.get("seed")])
    plan = sets.build_plan(topics, size, method, mix, counts, _ints(P.get("locks")), adjust, seed[0] if seed else None)
    return JsonResponse({"ok": True, **plan})
