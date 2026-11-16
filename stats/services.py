"""Natijalar va statistika hisob-kitoblari."""
from collections import defaultdict

from django.db.models import Count, Sum

from quiz import ranking
from quiz.models import Answer, Participant, PowerUpCode, PowerUpLog


def results_rows(room):
    total_q = room.room_questions.count()
    parts = list(
        Participant.objects.filter(room=room)
        .exclude(status=Participant.Status.PENDING)
        .select_related("school_class")
        .annotate(
            vcount=Count("violations", distinct=True),
            codes=Count("powerup_codes", distinct=True),
        )
    )
    rank_map = {p.id: r for p, r in ranking.standings(room)}
    answers = defaultdict(list)
    for a in Answer.objects.filter(participant__room=room).order_by("answered_at"):
        answers[a.participant_id].append(a)
    stolen = dict(
        PowerUpLog.objects.filter(room=room, type="steal")
        .values_list("attacker_id")
        .annotate(s=Sum("points_amount"))
    )
    lost = dict(
        PowerUpLog.objects.filter(room=room, type="steal")
        .values_list("victim_id")
        .annotate(s=Sum("points_amount"))
    )
    frozen = dict(
        PowerUpLog.objects.filter(room=room, type="freeze")
        .values_list("victim_id")
        .annotate(s=Sum("freeze_seconds"))
    )
    rows = []
    for p in parts:
        ans = answers.get(p.id, [])
        correct = sum(1 for a in ans if a.is_correct)
        percent = round(correct * 100 / len(ans), 1) if ans else 0
        rounds = max((a.round for a in ans), default=0)
        spent = 0
        if ans:
            spent = int((ans[-1].answered_at - ans[0].answered_at).total_seconds() + ans[0].response_ms / 1000)
        rows.append(
            {
                "id": p.id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "school_class": p.school_class.name,
                "correct": correct,
                "answered": len(ans),
                "total": len(ans),
                "rounds": rounds,
                "frozen_seconds": frozen.get(p.id, 0),
                "score": p.score,
                "percent": percent,
                "grade": room.grade_for_percent(percent),
                "rank": rank_map.get(p.id),
                "violations": p.vcount,
                "spent_seconds": spent,
                "is_late": p.is_late,
                "codes": p.codes,
                "stolen": stolen.get(p.id, 0),
                "lost": lost.get(p.id, 0),
                "status": p.status,
            }
        )
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["last_name"]))
    return rows


def fmt_seconds(s):
    return f"{s // 60}:{s % 60:02d}"


def stats(room):
    """Savol, mavzu, o'quvchi×mavzu va sinflar bo'yicha statistika."""
    rqs = {rq.id: rq for rq in room.room_questions.all()}
    per_q = defaultdict(lambda: [0, 0])  # [javoblar, xatolar]
    per_topic = defaultdict(lambda: [0, 0])
    matrix = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    names = {
        p.id: f"{p.first_name} {p.last_name} ({p.school_class.name})"
        for p in Participant.objects.filter(room=room).select_related("school_class")
    }
    attempts = defaultdict(list)  # (pid, rqid) -> [(aylana, to'g'rimi)]
    for pid, rqid, ok, rnd in Answer.objects.filter(participant__room=room).values_list(
        "participant_id", "room_question_id", "is_correct", "round"
    ):
        if rqid not in rqs:
            continue
        topic = rqs[rqid].snapshot.get("topic", "—")
        attempts[(pid, rqid)].append((rnd, ok))
        for bucket in (per_q[rqid], per_topic[topic], matrix[pid][topic]):
            bucket[0] += 1
            bucket[1] += 0 if ok else 1
    topic_order = {}
    for rq in rqs.values():
        topic_order.setdefault(rq.snapshot.get("topic", "—"), rq.snapshot.get("topic_order") or 0)

    def pct(b):
        return round(b[1] * 100 / b[0], 1) if b[0] else 0.0

    questions = sorted(
        (
            {
                "order": rq.order + 1,
                "text": rq.snapshot["text"],
                "topic": rq.snapshot.get("topic", "—"),
                "answered": per_q[rid][0],
                "wrong": per_q[rid][1],
                "error_percent": pct(per_q[rid]),
            }
            for rid, rq in rqs.items()
        ),
        key=lambda x: -x["error_percent"],
    )
    topics = sorted(
        (
            {"topic": t, "answered": b[0], "wrong": b[1], "error_percent": pct(b)}
            for t, b in per_topic.items()
        ),
        key=lambda x: -x["error_percent"],
    )
    topic_names = [t["topic"] for t in topics]
    student_topic = [
        {
            "name": names[pid],
            "cells": [
                {"wrong": matrix[pid][t][1], "answered": matrix[pid][t][0], "percent": pct(matrix[pid][t])}
                if t in matrix[pid]
                else None
                for t in topic_names
            ],
        }
        for pid in sorted(matrix, key=lambda i: names[i])
    ]
    by_class = defaultdict(list)
    for r in results_rows(room):
        if r["answered"] or r["status"] == "finished":
            by_class[r["school_class"]].append(r)
    classes = sorted(
        (
            {
                "name": c,
                "students": len(rs),
                "avg_score": round(sum(r["score"] for r in rs) / len(rs), 1),
                "avg_percent": round(sum(r["percent"] for r in rs) / len(rs), 1),
            }
            for c, rs in by_class.items()
        ),
        key=lambda x: -x["avg_score"],
    )
    # --- mavzu tartibi bo'yicha xato foizi (yig'ma to'plamlarda qiynalish nuqtasi)
    ordered_topics = sorted(per_topic, key=lambda t: (topic_order.get(t, 0), t))
    topic_line = [
        {"topic": t, "order": topic_order.get(t, 0), "error_percent": pct(per_topic[t]), "answered": per_topic[t][0]}
        for t in ordered_topics
    ]
    struggle = []
    for pid in sorted(matrix, key=lambda i: names[i]):
        first = next(
            (t for t in ordered_topics if matrix[pid][t][0] >= 2 and pct(matrix[pid][t]) >= STRUGGLE_PERCENT), None
        )
        if first:
            struggle.append({"name": names[pid], "topic": first, "error_percent": pct(matrix[pid][first])})
    class_first = next((t for t in topic_line if t["answered"] >= 2 and t["error_percent"] >= STRUGGLE_PERCENT), None)

    # --- o'rganish ko'rsatkichi: xato qilingan savol keyingi aylanada to'g'ri topildimi
    learn = {"repeated": 0, "learned": 0}
    per_student_learn = defaultdict(lambda: [0, 0])
    per_topic_learn = defaultdict(lambda: [0, 0])
    for (pid, rqid), lst in attempts.items():
        lst.sort()
        if len(lst) >= 2 and not lst[0][1]:  # birinchi urinish xato, takror berilgan
            ok2 = lst[1][1]
            learn["repeated"] += 1
            learn["learned"] += 1 if ok2 else 0
            per_student_learn[pid][0] += 1
            per_student_learn[pid][1] += 1 if ok2 else 0
            tp = rqs[rqid].snapshot.get("topic", "—")
            per_topic_learn[tp][0] += 1
            per_topic_learn[tp][1] += 1 if ok2 else 0
    learn["percent"] = round(learn["learned"] * 100 / learn["repeated"], 1) if learn["repeated"] else None
    learn["students"] = sorted(
        (
            {"name": names[pid], "repeated": b[0], "learned": b[1], "percent": round(b[1] * 100 / b[0], 1)}
            for pid, b in per_student_learn.items()
        ),
        key=lambda x: (-x["percent"], x["name"]),
    )
    learn["topics"] = sorted(
        (
            {"topic": t, "repeated": b[0], "learned": b[1], "percent": round(b[1] * 100 / b[0], 1)}
            for t, b in per_topic_learn.items()
        ),
        key=lambda x: x["percent"],
    )
    return {
        "questions": questions,
        "topics": topics,
        "topic_names": topic_names,
        "student_topic": student_topic,
        "classes": classes,
        "topic_line": topic_line,
        "struggle": struggle,
        "class_struggle": class_first,
        "learning": learn,
        "rounds_max": max((a[0] for lst in attempts.values() for a in lst), default=0),
    }


STRUGGLE_PERCENT = 50  # shu foiz va undan ko'p xato -> "qiynalmoqda"


def sets_difficulty(teacher):
    """To'plamlar bo'yicha (barcha xonalarda): qaysi to'plam eng qiyin chiqdi + mavzular kesimi."""
    from collections import OrderedDict

    from rooms.models import Room, RoomQuestion

    res = []
    rooms = Room.objects.filter(teacher=teacher, question_set__isnull=False).select_related("question_set")
    by_set = defaultdict(list)
    for r in rooms:
        by_set[r.question_set_id].append(r)
    for sid, rs in by_set.items():
        qs = rs[0].question_set
        rq_topic = {}
        for rq in RoomQuestion.objects.filter(room__in=rs):
            rq_topic[rq.id] = (rq.snapshot.get("topic", "—"), rq.snapshot.get("topic_order") or 0)
        total = [0, 0]
        per_topic = OrderedDict()
        for rqid, ok in Answer.objects.filter(participant__room__in=rs).values_list("room_question_id", "is_correct"):
            if rqid not in rq_topic:
                continue
            t, o = rq_topic[rqid]
            b = per_topic.setdefault(t, [o, 0, 0])
            b[1] += 1
            b[2] += 0 if ok else 1
            total[0] += 1
            total[1] += 0 if ok else 1
        if not total[0]:
            continue
        res.append(
            {
                "id": qs.id,
                "name": qs.name,
                "type": qs.set_type,
                "type_label": qs.get_set_type_display(),
                "rooms": len(rs),
                "answered": total[0],
                "error_percent": round(total[1] * 100 / total[0], 1),
                "topics": sorted(
                    (
                        {"topic": t, "order": b[0], "answered": b[1], "error_percent": round(b[2] * 100 / b[1], 1)}
                        for t, b in per_topic.items()
                    ),
                    key=lambda x: (x["order"], x["topic"]),
                ),
            }
        )
    res.sort(key=lambda x: -x["error_percent"])
    return res
