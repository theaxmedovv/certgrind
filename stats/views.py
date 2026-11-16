from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from openpyxl import Workbook
from openpyxl.styles import Font

from rooms.views import _room

from . import services


@login_required
def results(request, pk):
    room = _room(request, pk)
    rows = services.results_rows(room)
    for r in rows:
        r["time"] = services.fmt_seconds(r["spent_seconds"])
    return render(request, "teacher/results.html", {"room": room, "rows": rows})


@login_required
def results_export(request, pk):
    room = _room(request, pk)
    wb = Workbook()
    ws = wb.active
    ws.title = "Natijalar"
    headers = [
        "Ism", "Familiya", "Sinf", "Jami javoblar", "To'g'ri javoblar", "Foiz (%)", "Ball", "Baho", "O'rin",
        "Aylanalar soni", "Qoidabuzarliklar soni", "Sarflangan vaqt", "Kech kirgan", "Olingan maxfiy kodlar",
        "O'g'irlangan ball", "Yo'qotilgan ball", "Muzlatilgan soniyalar",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in services.results_rows(room):
        ws.append(
            [
                r["first_name"], r["last_name"], r["school_class"], r["answered"], r["correct"], r["percent"],
                r["score"], r["grade"], r["rank"] or "—", r["rounds"], r["violations"],
                services.fmt_seconds(r["spent_seconds"]), "Ha" if r["is_late"] else "Yo'q",
                r["codes"], r["stolen"], r["lost"], r["frozen_seconds"],
            ]
        )
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(12, len(str(col[0].value)) + 4)
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="natijalar_{room.code}.xlsx"'
    return resp


@login_required
def room_stats(request, pk):
    room = _room(request, pk)
    return render(request, "teacher/stats.html", {"room": room, "s": services.stats(room)})


@login_required
def sets_stats(request):
    """To'plamlar bo'yicha qiyinlik: barcha o'tkazilgan xonalar bo'yicha jamlanma."""
    return render(request, "teacher/sets_stats.html", {"sets": services.sets_difficulty(request.user)})
