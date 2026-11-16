from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .models import Question, QuestionOption, SchoolClass, Subject, Topic


@login_required
def question_list(request):
    qs = Question.objects.filter(teacher=request.user).select_related("topic")
    q = request.GET.get("q", "").strip()
    topic = request.GET.get("topic", "")
    diff = request.GET.get("difficulty", "")
    if q:
        qs = qs.filter(Q(text__icontains=q) | Q(options__text__icontains=q)).distinct()
    if topic:
        qs = qs.filter(topic_id=topic)
    if diff:
        qs = qs.filter(difficulty=diff)
    page = Paginator(qs.prefetch_related("options"), 20).get_page(request.GET.get("page"))
    return render(
        request,
        "teacher/question_list.html",
        {
            "page": page,
            "topics": Topic.objects.filter(teacher=request.user).annotate(n=Count("questions")),
            "q": q,
            "sel_topic": topic,
            "sel_diff": diff,
            "difficulties": Question.Difficulty.choices,
        },
    )


def _parse_options(post):
    texts = [t.strip() for t in post.getlist("opt_text")]
    try:
        correct = int(post.get("correct", "-1"))
    except ValueError:
        correct = -1
    opts = [(i, t) for i, t in enumerate(texts) if t]
    errors = []
    if not 2 <= len(opts) <= 6:
        errors.append("Javob variantlari soni 2 dan 6 gacha bo'lishi kerak")
    if correct not in [i for i, _ in opts]:
        errors.append("To'g'ri javobni tanlang (bo'sh variant to'g'ri bo'la olmaydi)")
    return opts, correct, errors


@login_required
def question_edit(request, pk=None):
    question = get_object_or_404(Question, pk=pk, teacher=request.user) if pk else None
    errors = []
    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        topic_name = request.POST.get("topic", "").strip()
        diff = request.POST.get("difficulty", Question.Difficulty.MEDIUM)
        opts, correct, errors = _parse_options(request.POST)
        if not text:
            errors.append("Savol matnini kiriting")
        if not topic_name:
            errors.append("Mavzuni kiriting")
        if diff not in Question.Difficulty.values:
            diff = Question.Difficulty.MEDIUM
        if not errors:
            with transaction.atomic():
                topic = services.get_topic(request.user, topic_name)
                if question is None:
                    question = Question(teacher=request.user)
                question.text, question.topic, question.difficulty = text, topic, diff
                question.code = request.POST.get("code", "").rstrip()
                question.input_values = request.POST.get("input_values", "").strip()[:300]
                if request.FILES.get("image"):
                    question.image = request.FILES["image"]
                elif request.POST.get("remove_image"):
                    question.image = None
                question.save()
                question.options.all().delete()
                QuestionOption.objects.bulk_create(
                    [QuestionOption(question=question, text=t[:500], is_correct=(i == correct)) for i, t in opts]
                )
            messages.success(request, "Savol saqlandi")
            return redirect("question_list")
    if question and request.method == "GET":
        opt_rows = [{"text": o.text, "correct": o.is_correct} for o in question.options.all()]
    elif request.method == "POST":
        opt_rows = [
            {"text": t, "correct": i == int(request.POST.get("correct", -1) or -1)}
            for i, t in enumerate(request.POST.getlist("opt_text"))
        ]
    else:
        opt_rows = [{"text": "", "correct": True}, {"text": "", "correct": False}]
    return render(
        request,
        "teacher/question_form.html",
        {
            "question": question,
            "errors": errors,
            "topics": Topic.objects.filter(teacher=request.user),
            "difficulties": Question.Difficulty.choices,
            "opt_rows": opt_rows,
            "form_data": request.POST if request.method == "POST" else None,
            "q_code": request.POST.get("code", "") if request.method == "POST" else (question.code if question else ""),
            "q_text": request.POST.get("text", "") if request.method == "POST" else (question.text if question else ""),
        },
    )


@login_required
@require_POST
def question_delete(request, pk):
    get_object_or_404(Question, pk=pk, teacher=request.user).delete()
    messages.success(request, "Savol o'chirildi (eski xonalardagi nusxalari saqlanadi)")
    return redirect("question_list")


@login_required
def question_import(request):
    """Excel (3 varaq) yuklanadi; to'g'ri qatorlar saqlanadi, xatolilar jadvalda ko'rsatiladi."""
    subjects = Subject.objects.filter(teacher=request.user)
    ctx = {"report": None, "subjects": subjects}
    if request.method == "POST" and request.FILES.get("file"):
        name = (request.POST.get("subject_new") or request.POST.get("subject") or "Python").strip()
        ctx["report"] = services.import_workbook(
            request.FILES["file"], request.user, subject_name=name, grade=request.POST.get("grade", "")
        )
    return render(request, "teacher/import.html", ctx)


@login_required
def import_template(request):
    resp = HttpResponse(
        services.build_template(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = 'attachment; filename="savollar_shablon.xlsx"'
    return resp


@login_required
def subject_export(request, pk):
    subject = get_object_or_404(Subject, pk=pk, teacher=request.user)
    resp = HttpResponse(
        services.export_subject(subject),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="fan_{subject.pk}.xlsx"'
    return resp


RECOMMENDED = 15


@login_required
def subject_list(request):
    """Fanlar va mavzular: tartib (drag & drop), savollar soni va qiyinlik taqsimoti."""
    subjects = []
    for subj in Subject.objects.filter(teacher=request.user):
        topics = list(
            subj.topics.annotate(
                n=Count("questions"),
                easy=Count("questions", filter=Q(questions__difficulty="easy")),
                medium=Count("questions", filter=Q(questions__difficulty="medium")),
                hard=Count("questions", filter=Q(questions__difficulty="hard")),
            ).order_by("order", "id")
        )
        for t in topics:
            t.low = t.n < RECOMMENDED
            total = t.n or 1
            t.pe, t.pm, t.ph = (round(t.easy * 100 / total), round(t.medium * 100 / total), round(t.hard * 100 / total))
        subj.topic_list = topics
        subj.total_questions = sum(t.n for t in topics)
        subjects.append(subj)
    return render(request, "teacher/subjects.html", {"subjects": subjects, "recommended": RECOMMENDED})


@login_required
@require_POST
def subject_create(request):
    name = request.POST.get("name", "").strip()
    if name:
        _, created = Subject.objects.get_or_create(
            teacher=request.user, name=name[:120], defaults={"grade": request.POST.get("grade", "")[:30]}
        )
        messages.success(request, f"'{name}' fani qo'shildi" if created else "Bu fan allaqachon bor")
    return redirect("subject_list")


@login_required
@require_POST
def subject_delete(request, pk):
    subj = get_object_or_404(Subject, pk=pk, teacher=request.user)
    try:
        with transaction.atomic():
            subj.delete()
        messages.success(request, "Fan o'chirildi")
    except ProtectedError:
        messages.error(request, "Fanda savollar bor — avval ularni o'chiring")
    return redirect("subject_list")


@login_required
@require_POST
def topic_create(request, subject_pk):
    subj = get_object_or_404(Subject, pk=subject_pk, teacher=request.user)
    name = request.POST.get("name", "").strip()
    if name:
        last = subj.topics.order_by("-order").values_list("order", flat=True).first() or 0
        Topic.objects.get_or_create(
            teacher=request.user, subject=subj, name=name[:120], defaults={"order": last + 1}
        )
    return redirect("subject_list")


@login_required
@require_POST
def topic_rename(request, pk):
    topic = get_object_or_404(Topic, pk=pk, teacher=request.user)
    name = request.POST.get("name", "").strip()
    if name and not Topic.objects.filter(subject=topic.subject, name=name[:120]).exclude(pk=pk).exists():
        topic.name = name[:120]
        topic.save(update_fields=["name"])
    return redirect("subject_list")


@login_required
@require_POST
def topic_delete(request, pk):
    topic = get_object_or_404(Topic, pk=pk, teacher=request.user)
    try:
        with transaction.atomic():
            topic.delete()
    except ProtectedError:
        messages.error(request, "Mavzuda savollar bor — avval ularni o'chiring")
    return redirect("subject_list")


@login_required
@require_POST
def topic_reorder(request, subject_pk):
    """Drag & drop: tanlangan tartibda mavzu id'lari ro'yxatini qabul qiladi."""
    import json

    subj = get_object_or_404(Subject, pk=subject_pk, teacher=request.user)
    try:
        ids = [int(i) for i in json.loads(request.body or "{}").get("ids", [])]
    except (ValueError, TypeError):
        return JsonResponse({"ok": False}, status=400)
    own = {t.pk: t for t in subj.topics.all()}
    if set(ids) != set(own):
        return JsonResponse({"ok": False, "error": "Mavzular ro'yxati mos emas"}, status=400)
    with transaction.atomic():
        for n, pk in enumerate(ids, 1):
            if own[pk].order != n:
                Topic.objects.filter(pk=pk).update(order=n)
    return JsonResponse({"ok": True})


@login_required
def classes(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            _, created = SchoolClass.objects.get_or_create(name=name[:20])
            messages.success(request, f"'{name}' qo'shildi" if created else "Bu sinf allaqachon bor")
        return redirect("classes")
    return render(request, "teacher/classes.html", {"classes": SchoolClass.objects.all()})


@login_required
@require_POST
def class_delete(request, pk):
    try:
        SchoolClass.objects.get(pk=pk).delete()
    except ProtectedError:
        messages.error(request, "Bu sinfda o'quvchilar bor, o'chirib bo'lmaydi")
    except SchoolClass.DoesNotExist:
        pass
    return redirect("classes")
