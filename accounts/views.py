from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def settings_page(request):
    u = request.user
    if request.method == "POST":
        u.first_name = request.POST.get("first_name", "").strip()[:150]
        u.last_name = request.POST.get("last_name", "").strip()[:150]
        u.save(update_fields=["first_name", "last_name"])
        messages.success(request, "Profil saqlandi")
        return redirect("settings")
    return render(request, "teacher/settings.html")
