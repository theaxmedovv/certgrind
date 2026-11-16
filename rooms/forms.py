from django import forms

from .models import Room


class RoomForm(forms.ModelForm):
    password = forms.CharField(label="Xona paroli", min_length=3, max_length=40)
    grade_5 = forms.IntegerField(label="«5» uchun (%) dan", min_value=1, max_value=100, initial=86)
    grade_4 = forms.IntegerField(label="«4» uchun (%) dan", min_value=1, max_value=100, initial=71)
    grade_3 = forms.IntegerField(label="«3» uchun (%) dan", min_value=1, max_value=100, initial=56)

    class Meta:
        model = Room
        fields = [
            "name",
            "duration_minutes",
            "interval_seconds",
            "powerups_enabled",
            "steal_enabled",
            "freeze_enabled",
            "steal_min_percent",
            "steal_max_percent",
            "freeze_min_seconds",
            "freeze_max_seconds",
        ]
        labels = {
            "name": "Xona nomi",
            "duration_minutes": "Umumiy vaqt (daqiqa)",
            "interval_seconds": "Oraliq ekran vaqti (1–10 soniya)",
            "powerups_enabled": "Maxfiy kod (super-kuchlar) yoqilgan",
            "steal_enabled": "💰 Ball o'g'irlash yoqilgan",
            "freeze_enabled": "❄️ Muzlatish yoqilgan",
            "steal_min_percent": "O'g'irlash: eng kam (%)",
            "steal_max_percent": "O'g'irlash: eng ko'p (%)",
            "freeze_min_seconds": "Muzlatish: eng kam (soniya)",
            "freeze_max_seconds": "Muzlatish: eng ko'p (soniya)",
        }

    def clean_duration_minutes(self):
        v = self.cleaned_data["duration_minutes"]
        if not 1 <= v <= 300:
            raise forms.ValidationError("1 dan 300 daqiqagacha")
        return v

    def clean(self):
        data = super().clean()
        lo, hi = data.get("steal_min_percent"), data.get("steal_max_percent")
        if lo is not None and hi is not None and not (1 <= lo <= hi <= 100):
            raise forms.ValidationError("O'g'irlash oralig'i: 1 ≤ eng kam ≤ eng ko'p ≤ 100 (%)")
        lo, hi = data.get("freeze_min_seconds"), data.get("freeze_max_seconds")
        if lo is not None and hi is not None and not (1 <= lo <= hi <= 120):
            raise forms.ValidationError("Muzlatish oralig'i: 1 ≤ eng kam ≤ eng ko'p ≤ 120 (soniya)")
        g5, g4, g3 = (data.get(k) for k in ("grade_5", "grade_4", "grade_3"))
        if None not in (g5, g4, g3) and not (g5 > g4 > g3):
            raise forms.ValidationError("Chegaralar «5» > «4» > «3» tartibida bo'lishi kerak")
        return data

    def thresholds(self):
        d = self.cleaned_data
        return {"5": d["grade_5"], "4": d["grade_4"], "3": d["grade_3"]}
