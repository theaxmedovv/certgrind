from collections import defaultdict
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from questions import sets as sets_lib
from questions.models import Question, QuestionSet, Subject, Topic

from .forms import RoomForm
from .models import Room
from .services import create_room_from_set, create_room_with_questions


def _room(request, pk):
    room = get_object_or_404(Room, pk=pk)
    if room.teacher_id != request.user.id and not request.user.is_superuser:
        raise Http404
    return room


def _join_url(request, room):
    return request.build_absolute_uri(reverse("join", args=[room.code]))


def greeting():
    h = timezone.localtime().hour
    if h < 5:
        return "Xayrli tun", "🌙"
    if h < 12:
        return "Xayrli tong", "☀️"
    if h < 18:
        return "Xayrli kun", "🌤️"
    return "Xayrli kech", "🌆"


@login_required
def dashboard(request):
    from quiz.models import Participant
    from stats import services as stats_services

    rooms = Room.objects.filter(teacher=request.user)
    done = rooms.filter(status=Room.Status.FINISHED)
    students = Participant.objects.filter(room__teacher=request.user).exclude(
        status=Participant.Status.PENDING
    )
    avg = students.filter(status=Participant.Status.FINISHED).aggregate(a=Avg("score"))["a"]
    # eng ko'p xato qilingan mavzular (oxirgi 10 ta yakunlangan test)
    agg = defaultdict(lambda: [0, 0])
    for r in done[:10]:
        for t in stats_services.stats(r)["topics"]:
            agg[t["topic"]][0] += t["answered"]
            agg[t["topic"]][1] += t["wrong"]
    hard = sorted(
        (
            {"topic": t, "percent": round(v[1] * 100 / v[0], 1)}
            for t, v in agg.items()
            if v[0]
        ),
        key=lambda x: -x["percent"],
    )[:6]
    hello, emoji = greeting()
    name = request.user.first_name or request.user.username
    return render(
        request,
        "teacher/dashboard.html",
        {
            "rooms": rooms[:6],
            "greeting": f"{hello}, {name}! {emoji}",
            "cards": {
                "questions": Question.objects.filter(teacher=request.user).count(),
                "rooms": done.count(),
                "students": students.count(),
                "avg": round(avg) if avg else 0,
            },
            "hard_topics": hard,
        },
    )


@login_required
def room_list(request, mode="rooms"):
    """mode: rooms | results | stats — xonalar ro'yxati."""
    qs = Room.objects.filter(teacher=request.user).annotate(
        n_students=Count("participants", distinct=True)
    )
    if mode in ("results", "stats"):
        qs = qs.filter(status=Room.Status.FINISHED)
    titles = {"rooms": "Xonalar", "results": "Natijalar", "stats": "Statistika"}
    return render(
        request,
        "teacher/room_list.html",
        {"rooms": qs, "mode": mode, "title": titles[mode]},
    )


@login_required
def room_create(request):
    sets_qs = QuestionSet.objects.filter(teacher=request.user).select_related("subject").prefetch_related("topics")
    form = RoomForm(request.POST or None)
    selected = request.POST.get("question_set") or request.GET.get("set") or ""
    if request.method == "POST" and form.is_valid():
        qset = sets_qs.filter(pk=selected).first() if selected.isdigit() else None
        if qset is None:
            form.add_error(None, "To'plamni tanlang")
        elif not qset.items.exists():
            form.add_error(None, "Tanlangan to'plam bo'sh")
        else:
            data = {k: v for k, v in form.cleaned_data.items() if k not in ("grade_5", "grade_4", "grade_3")}
            data["grade_thresholds"] = form.thresholds()
            room = create_room_from_set(request.user, data, qset)
            return redirect("room_ready", pk=room.pk)
    subjects = list(Subject.objects.filter(teacher=request.user))
    topics_data = {
        s.pk: [{"id": t.pk, "name": t.name, "order": t.order, "n": t.n}
               for t in s.topics.annotate(n=Count("questions")).order_by("order", "id")]
        for s in subjects
    }
    sets_data = [
        {"id": q.pk, "name": q.name, "type": q.set_type, "type_label": q.get_set_type_display(),
         "count": q.items.count(), "subject": q.subject_id,
         "topics": [t.name for t in sorted(q.topics.all(), key=lambda t: t.order)][:4]}
        for q in sets_qs
    ]
    return render(
        request,
        "teacher/room_form.html",
        {
            "form": form,
            "sets_data": sets_data,
            "subjects": subjects,
            "topics_data": topics_data,
            "selected": int(selected) if selected.isdigit() else 0,
            "sizes": sets_lib.SIZES,
            "seconds_per_question": sets_lib.SECONDS_PER_QUESTION,
        },
    )


@login_required
def room_ready(request, pk):
    room = _room(request, pk)
    return render(request, "teacher/room_ready.html", {"room": room, "join_url": _join_url(request, room)})


@login_required
def room_control(request, pk):
    room = _room(request, pk)
    return render(request, "teacher/room_control.html", {"room": room, "join_url": _join_url(request, room)})


@login_required
def room_screen(request, pk):
    room = _room(request, pk)
    return render(request, "teacher/room_screen.html", {"room": room, "join_url": _join_url(request, room)})


@login_required
def room_qr(request, pk):
    room = _room(request, pk)
    img = qrcode.make(_join_url(request, room), box_size=12, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@login_required
@require_POST
def room_results_visible(request, pk):
    from quiz import services

    room = _room(request, pk)
    value = request.POST.get("value") == "1"
    services.set_results_visible(room.id, value)
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "value": value})
    messages.success(request, "O'quvchilar natijalarni ko'ra oladi" if value else "Natijalar yopildi")
    return redirect("results", pk=room.pk)


@login_required
@require_POST
def room_delete(request, pk):
    _room(request, pk).delete()
    messages.success(request, "Xona o'chirildi")
    return redirect("dashboard")
