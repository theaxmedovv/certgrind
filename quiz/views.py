import json

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from questions.models import SchoolClass
from rooms.models import Room

from . import services
from .services import GameError


def home(request):
    code = request.GET.get("code", "").strip()
    if code:
        return redirect("join", code=code)
    return render(request, "student/home.html")


def join_page(request, code):
    room = Room.objects.filter(code=code).first()
    return render(
        request,
        "student/join.html",
        {
            "code": code,
            "room": room,
            "classes": SchoolClass.objects.all(),
            "avatars": services.AVATARS,
        },
    )


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "?")


@require_POST
def join_api(request):
    # parolni taxmin qilishdan himoya: IP bo'yicha daqiqasiga 20 urinish
    key = f"joinrate:{_client_ip(request)}"
    try:
        cache.add(key, 0, 60)
        if cache.incr(key) > 20:
            return JsonResponse({"ok": False, "message": "Juda ko'p urinish. Bir daqiqa kuting."}, status=429)
    except Exception:
        pass
    try:
        data = json.loads(request.body or "{}")
        p = services.join_room(
            data.get("code"),
            data.get("password"),
            data.get("first_name"),
            data.get("last_name"),
            data.get("school_class"),
            data.get("avatar"),
        )
    except GameError as e:
        return JsonResponse({"ok": False, "message": e.message, "code": e.code}, status=400)
    except ValueError:
        return JsonResponse({"ok": False, "message": "Noto'g'ri so'rov"}, status=400)
    resp = JsonResponse({"ok": True, "token": p.session_token})
    # token cookie'da ham saqlanadi: WebSocket faqat shu brauzerdan ochila oladi
    resp.set_cookie("pt", p.session_token, max_age=86400, httponly=True, samesite="Lax")
    return resp


def play(request):
    return render(request, "student/play.html")
