import json
import re

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .models import PcepAttempt, PcepModule, PcepQuestion


def _stats(qs):
    """Tugatilgan urinishlar bo'yicha oxirgi va eng yaxshi natija."""
    done = list(qs.filter(finished_at__isnull=False).order_by("-finished_at")[:50])
    if not done:
        return None
    return {"last": round(done[0].percent), "best": round(max(a.percent for a in done)), "count": len(done)}


def home(request):
    mine = services.attempts_for(request)
    modules = []
    for m in PcepModule.objects.order_by("number"):
        modules.append({
            "m": m,
            "n": PcepQuestion.objects.filter(bank="module", module=m).count(),
            "st": _stats(mine.filter(mode="module", module=m)),
        })
    ctx = {
        "modules": modules,
        "mixed_n": PcepQuestion.objects.filter(bank="module").count(),
        "mixed_st": _stats(mine.filter(mode__in=["mixed", "exam"])),
        "practice": {"n": PcepQuestion.objects.filter(bank="practice").count(), "st": _stats(mine.filter(mode="practice"))},
        "final": {"n": PcepQuestion.objects.filter(bank="final").count(), "st": _stats(mine.filter(mode="final"))},
    }
    return render(request, "pcep/home.html", ctx)


@require_POST
def start(request, kind):
    module = None
    if kind in ("1", "2", "3", "4"):
        module = get_object_or_404(PcepModule, number=int(kind))
        kind = "module"
    elif kind not in ("mixed", "exam", "practice", "final"):
        raise Http404
    try:
        size = int(request.POST.get("size", 30))
    except ValueError:
        size = 30
    if size not in (0, 10, 20, 30):
        size = 30
    if kind == "mixed" and size == 0:
        size = 60
    timed = request.POST.get("timed") == "1" or kind in ("exam", "practice", "final")
    attempt = services.create_attempt(request, kind, size=size, timed=timed, module=module)
    if attempt is None:
        return redirect("pcep:home")
    return redirect("pcep:attempt", attempt.id)


def _get_attempt(request, attempt_id):
    attempt = get_object_or_404(PcepAttempt, id=attempt_id)
    if not services.can_access(request, attempt):
        raise Http404
    return attempt


def _template_lines(template):
    """Kod shablonini qatorlarga va (matn | katak) bo'laklarga ajratadi."""
    lines = []
    for line in template.split(chr(10)):
        parts = []
        for seg in re.split(r"(\{\{g\d+\}\})", line):
            if not seg:
                continue
            m = re.fullmatch(r"\{\{(g\d+)\}\}", seg)
            parts.append({"slot": m.group(1)} if m else {"t": seg})
        lines.append(parts)
    return lines


def _client_item(a):
    """Brauzerga yuboriladigan savol ma'lumoti. To'g'ri javoblar YUBORILMAYDI."""
    q = a.question
    base = {
        "id": q.id, "kind": q.question_type, "text": q.text, "code": q.code,
        "module": q.module.number if q.module else None, "flagged": a.flagged,
    }
    if q.question_type in PcepQuestion.INTERACTIVE:
        ix = q.interaction
        pool = {b["id"]: b for b in (ix.get("blocks") or ix.get("items") or [])}
        ordered = [pool[i] for i in a.option_order if i in pool] or list(pool.values())
        base["response"] = a.response or {}
        if q.question_type == "match":
            base.update(blocks=ordered, targets=ix["targets"])
        elif q.question_type == "order":
            base.update(blocks=ordered, top_label=ix.get("top_label", ""), bottom_label=ix.get("bottom_label", ""))
        elif q.question_type == "categorize":
            base.update(blocks=ordered, categories=ix["categories"], prefilled=ix.get("prefilled", {}))
        else:  # code_gap
            n_slots = len(ix["answer"])
            base.update(blocks=ordered, lines=_template_lines(ix["template"]), n_slots=n_slots,
                        decoys=len(ix["blocks"]) > n_slots)
        return base
    opts = {o.id: o for o in q.options.all()}
    n_correct = sum(1 for o in opts.values() if o.is_correct)
    base.update(
        multiple=q.question_type == "multiple", n_correct=n_correct,  # faqat soni, qaysilari emas
        options=[{"id": oid, "text": opts[oid].text} for oid in a.option_order if oid in opts],
        selected=a.selected_option_ids,
    )
    return base


def attempt_view(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    if attempt.finished_at:
        return redirect("pcep:result", attempt.id)
    answers = attempt.answers.select_related("question", "question__module")
    items = [_client_item(a) for a in answers]
    limit = services.time_limit(attempt)
    remaining = None
    if limit:
        remaining = max(0, limit - int((timezone.now() - attempt.started_at).total_seconds()))
    data = {
        "attempt": attempt.id,
        "items": items,
        "remaining": remaining,
        "save_url": f"/pcep/attempt/{attempt.id}/save/",
        "finish_url": f"/pcep/attempt/{attempt.id}/finish/",
    }
    return render(request, "pcep/attempt.html", {"attempt": attempt, "data": data})


@require_POST
def save(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    if attempt.finished_at:
        return JsonResponse({"ok": False, "finished": True})
    try:
        body = json.loads(request.body)
        qid = int(body["qid"])
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False}, status=400)
    ans = get_object_or_404(attempt.answers.select_related("question"), question_id=qid)
    q = ans.question
    try:
        if q.question_type in PcepQuestion.INTERACTIVE:
            clean = services.sanitize_response(q, body.get("response"))
            if clean is None:
                return JsonResponse({"ok": False}, status=400)
            ans.response = clean
        else:
            valid = set(ans.option_order)
            ans.selected_option_ids = [int(i) for i in body.get("selected", []) if int(i) in valid]
    except (ValueError, TypeError):
        return JsonResponse({"ok": False}, status=400)
    ans.flagged = bool(body.get("flagged"))
    ans.save(update_fields=["response", "selected_option_ids", "flagged"])
    return JsonResponse({"ok": True})


@require_POST
def finish(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    services.finish_attempt(attempt)
    return JsonResponse({"ok": True, "url": f"/pcep/attempt/{attempt.id}/result/"})


def result(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    if not attempt.finished_at:
        return redirect("pcep:attempt", attempt.id)
    bd = services.module_breakdown(attempt)
    weak = services.weakest_module(bd)
    ok = services.passed(attempt.percent)
    need = -(-attempt.total * services.PASS_PERCENT // 100)
    partial = {"wrong": 0, "ok": 0, "total": 0}
    for a in attempt.answers.select_related("question").filter(question__question_type__in=PcepQuestion.INTERACTIVE, is_correct=False):
        rep = services.slot_report(a.question, a.response or {})
        partial["wrong"] += 1
        partial["ok"] += rep["ok"]
        partial["total"] += rep["total"]
    return render(request, "pcep/result.html", {
        "partial": partial if partial["wrong"] else None,
        "attempt": attempt, "passed": ok, "missing": max(0, need - attempt.correct),
        "breakdown": bd, "weak": weak if weak and weak["pct"] < 100 else None,
        "mins": attempt.duration_seconds // 60, "secs": attempt.duration_seconds % 60,
        "wrong_count": attempt.total - attempt.correct,
    })


def _interactive_card(a):
    """Interaktiv savol uchun: o'quvchi javobi va to'g'ri javob yonma-yon (ko'rib chiqish ekrani)."""
    q, ix = a.question, a.question.interaction
    resp = a.response or {}
    rep = services.slot_report(q, resp)
    t = q.question_type
    if t == "order":
        txt = {i["id"]: i["text"] for i in ix["items"]}
        got = resp.get("order") or []
        rows = [{"pos": i + 1, "user": txt.get(got[i]) if i < len(got) else None, "right": txt[ix["answer"][i]],
                 "ok": rep["slots"][str(i)]} for i in range(len(ix["answer"]))]
        return {"kind": t, "rows": rows, "top": ix.get("top_label", ""), "bottom": ix.get("bottom_label", ""), "rep": rep}
    slots = resp.get("slots") or {}
    if t == "match":
        txt = {i["id"]: i["text"] for i in ix["items"]}
        rows = [{"label": tg["text"], "user": txt.get(slots.get(tg["id"])), "right": txt[rep["best"][tg["id"]]],
                 "ok": rep["slots"][tg["id"]]} for tg in ix["targets"]]
        return {"kind": t, "rows": rows, "rep": rep}
    if t == "categorize":
        txt = {i["id"]: i["text"] for i in ix["items"]}
        cat = {c["id"]: c["label"] for c in ix["categories"]}
        rows = [{"label": txt[k], "user": cat.get(slots.get(k)), "right": cat[v], "ok": rep["slots"][k]}
                for k, v in rep["best"].items()]
        pre = [{"label": txt[k], "right": cat[v]} for k, v in ix.get("prefilled", {}).items()]
        return {"kind": t, "rows": rows, "pre": pre, "rep": rep}
    # code_gap
    txt = {b["id"]: b["text"] for b in ix["blocks"]}
    lines = []
    for line in _template_lines(ix["template"]):
        segs = []
        for p in line:
            if "slot" in p:
                g = p["slot"]
                segs.append({"slot": g, "user": txt.get(slots.get(g)), "right": txt[rep["best"][g]], "ok": rep["slots"][g]})
            else:
                segs.append(p)
        lines.append(segs)
    unused = [b["text"] for b in ix["blocks"] if b["id"] not in set(ix["answer"].values())]
    return {"kind": t, "lines": lines, "solution": ix.get("solution", ""), "result": ix.get("result", ""),
            "unused": unused, "rep": rep}


def review(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    if not attempt.finished_at:
        return redirect("pcep:attempt", attempt.id)
    cards = []
    for a in attempt.answers.select_related("question", "question__module"):
        q = a.question
        card = {"n": a.order + 1, "q": q, "ans": a, "ex": q.explanation_uz or {}}
        if q.question_type in PcepQuestion.INTERACTIVE:
            card["inter"] = _interactive_card(a)
            card["skipped"] = not card["inter"]["rep"]["ok"] and not (a.response or {})
        else:
            chosen = set(a.selected_option_ids or [])
            opts = {o.id: o for o in q.options.all()}
            card["options"] = [{"text": opts[i].text, "correct": opts[i].is_correct, "chosen": i in chosen}
                               for i in a.option_order if i in opts]
            card["skipped"] = not chosen
        cards.append(card)
    return render(request, "pcep/review.html", {"attempt": attempt, "cards": cards})


@require_POST
def retry_mistakes(request, attempt_id):
    attempt = _get_attempt(request, attempt_id)
    ids = list(attempt.answers.filter(is_correct=False).values_list("question_id", flat=True))
    new = services.create_attempt(request, "mistakes", only_ids=ids, timed=False) if ids else None
    return redirect("pcep:attempt", new.id) if new else redirect("pcep:result", attempt.id)


def stats(request):
    mine = services.attempts_for(request)
    done = mine.filter(finished_at__isnull=False).order_by("finished_at")
    history = list(done.order_by("-finished_at")[:20])
    series = {}
    for a in done:
        key = f"{a.module.number}-modul" if a.mode == "module" and a.module else {"mixed": "Aralash", "exam": "Aralash", "practice": "Practice", "final": "Final"}.get(a.mode)
        if key:
            series.setdefault(key, []).append({"x": a.finished_at.strftime("%d.%m %H:%M"), "y": round(a.percent)})
    labels = {a.finished_at.strftime("%d.%m %H:%M") for a in done}
    return render(request, "pcep/stats.html", {
        "history": history, "series": series, "sections": services.section_stats(mine),
        "ready": services.readiness(mine), "has_data": bool(history),
    })
