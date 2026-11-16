import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def default_grade_thresholds():
    # Foiz chegaralari: shu foiz va undan yuqori -> baho
    return {"5": 86, "4": 71, "3": 56}


class Room(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Kutilmoqda"
        RUNNING = "running", "Davom etmoqda"
        PAUSED = "paused", "Pauza"
        FINISHED = "finished", "Yakunlangan"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rooms"
    )
    question_set = models.ForeignKey(
        "questions.QuestionSet", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rooms", verbose_name="To'plam",
    )
    name = models.CharField("Xona nomi", max_length=150)
    code = models.CharField("Xona raqami", max_length=6, unique=True, db_index=True)
    password = models.CharField("Parol (hash)", max_length=128)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.WAITING
    )
    duration_minutes = models.PositiveIntegerField("Umumiy vaqt (daqiqa)", default=20)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    total_paused_seconds = models.PositiveIntegerField(default=0)
    interval_seconds = models.PositiveSmallIntegerField(
        "Oraliq ekran vaqti (soniya)",
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    results_visible = models.BooleanField("Natijalar ko'rinadi", default=False)
    powerups_enabled = models.BooleanField("Maxfiy kod yoqilgan", default=True)
    steal_enabled = models.BooleanField("O'g'irlash yoqilgan", default=True)
    freeze_enabled = models.BooleanField("Muzlatish yoqilgan", default=True)
    steal_percent = models.PositiveSmallIntegerField(
        "O'g'irlash foizi", default=10, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    freeze_seconds = models.PositiveSmallIntegerField("Muzlatish vaqti (soniya)", default=10)
    steal_min_percent = models.PositiveSmallIntegerField("O'g'irlash: min %", default=5)
    steal_max_percent = models.PositiveSmallIntegerField("O'g'irlash: max %", default=20)
    freeze_min_seconds = models.PositiveSmallIntegerField("Muzlatish: min soniya", default=5)
    freeze_max_seconds = models.PositiveSmallIntegerField("Muzlatish: max soniya", default=15)
    grade_thresholds = models.JSONField("Baho chegaralari", default=default_grade_thresholds)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Xona"
        verbose_name_plural = "Xonalar"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    # --- parol ---
    def set_password(self, raw):
        self.password = make_password(raw)

    def check_password(self, raw):
        return check_password(raw, self.password)

    # --- kod ---
    @staticmethod
    def generate_code():
        while True:
            code = f"{secrets.randbelow(900000) + 100000}"
            if not Room.objects.filter(code=code).exists():
                return code

    def grade_for_percent(self, percent):
        t = self.grade_thresholds or default_grade_thresholds()
        if percent >= t.get("5", 86):
            return 5
        if percent >= t.get("4", 71):
            return 4
        if percent >= t.get("3", 56):
            return 3
        return 2


class RoomQuestion(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="room_questions")
    # Asl savol o'chirilsa ham snapshot saqlanib qoladi
    question = models.ForeignKey(
        "questions.Question", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    order = models.PositiveIntegerField()
    # {"text", "topic", "image", "difficulty", "options": [{"id", "text", "is_correct"}]}
    snapshot = models.JSONField()

    class Meta:
        verbose_name = "Xona savoli"
        verbose_name_plural = "Xona savollari"
        ordering = ["room", "order"]
        constraints = [
            models.UniqueConstraint(fields=["room", "order"], name="uniq_room_question_order")
        ]

    def __str__(self):
        return f"{self.room.code} #{self.order}"


class RoomEvent(models.Model):
    class Type(models.TextChoices):
        START = "start", "Boshlandi"
        PAUSE = "pause", "Pauza"
        RESUME = "resume", "Davom ettirildi"
        ADD_TIME = "add_time", "Vaqt qo'shildi"
        LATE_JOIN = "late_join", "Kech kirish"
        FINISH = "finish", "Yakunlandi"
        OTHER = "other", "Boshqa"

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=20, choices=Type.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Xona hodisasi"
        verbose_name_plural = "Xona hodisalari"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.room.code} {self.type}"
