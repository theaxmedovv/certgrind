import secrets

from django.db import models


def generate_session_token():
    return secrets.token_urlsafe(32)


class Participant(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ruxsat kutmoqda"
        WAITING = "waiting", "Kutish xonasida"
        ACTIVE = "active", "Test yechmoqda"
        KICKED = "kicked", "Chetlatilgan"
        FINISHED = "finished", "Tugatgan"

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="participants")
    first_name = models.CharField("Ism", max_length=60)
    last_name = models.CharField("Familiya", max_length=60)
    school_class = models.ForeignKey(
        "questions.SchoolClass", on_delete=models.PROTECT, related_name="participants"
    )
    avatar = models.CharField(max_length=40, default="avatar1")
    session_token = models.CharField(
        max_length=64, unique=True, default=generate_session_token, db_index=True
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    is_late = models.BooleanField("Kech kirgan", default=False)
    score = models.IntegerField(default=0)
    streak = models.PositiveSmallIntegerField(default=0)
    current_index = models.PositiveIntegerField(default=0)
    current_round = models.PositiveIntegerField(default=1)
    extra_seconds = models.PositiveIntegerField(default=0)
    frozen_until = models.DateTimeField(null=True, blank=True)
    last_target = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "O'quvchi"
        verbose_name_plural = "O'quvchilar"
        ordering = ["joined_at"]
        indexes = [models.Index(fields=["room", "score"], name="participant_room_score_idx")]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.school_class})"


class ParticipantQuestion(models.Model):
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="question_order"
    )
    room_question = models.ForeignKey("rooms.RoomQuestion", on_delete=models.CASCADE, related_name="+")
    round = models.PositiveIntegerField(default=1)
    position = models.PositiveIntegerField()
    # Variant id'larining shu o'quvchi uchun aralashtirilgan tartibi
    option_order = models.JSONField(default=list)
    shown_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "O'quvchi savoli"
        verbose_name_plural = "O'quvchi savollari"
        ordering = ["participant", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "round", "position"], name="uniq_participant_round_position"
            ),
            models.UniqueConstraint(
                fields=["participant", "round", "room_question"], name="uniq_participant_round_rq"
            ),
        ]


class Answer(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="answers")
    room_question = models.ForeignKey(
        "rooms.RoomQuestion", on_delete=models.CASCADE, related_name="answers"
    )
    round = models.PositiveIntegerField(default=1)
    selected_option_id = models.BigIntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    points = models.PositiveIntegerField(default=0)
    response_ms = models.PositiveIntegerField(default=0)
    client_uuid = models.UUIDField(unique=True)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Javob"
        verbose_name_plural = "Javoblar"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "room_question", "round"], name="uniq_answer_participant_question_round"
            )
        ]
        indexes = [models.Index(fields=["room_question", "is_correct"], name="answer_rq_correct_idx")]


class Violation(models.Model):
    class Type(models.TextChoices):
        FULLSCREEN_EXIT = "fullscreen_exit", "Fullscreen'dan chiqish"
        TAB_SWITCH = "tab_switch", "Oyna/tab almashtirish"
        PRINTSCREEN = "printscreen", "PrintScreen"
        DEVTOOLS = "devtools", "DevTools"

    class Decision(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        ALLOWED = "allowed", "Ruxsat berildi"
        KICKED = "kicked", "Chiqarildi"

    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="violations"
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    occurred_at = models.DateTimeField(auto_now_add=True)
    decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Qoidabuzarlik"
        verbose_name_plural = "Qoidabuzarliklar"
        ordering = ["-occurred_at"]


class PowerUpCode(models.Model):
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="powerup_codes"
    )
    code = models.CharField(max_length=16, unique=True)
    is_used = models.BooleanField(default=False)
    earned_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Maxfiy kod"
        verbose_name_plural = "Maxfiy kodlar"


class PowerUpLog(models.Model):
    class Type(models.TextChoices):
        STEAL = "steal", "O'g'irlash"
        FREEZE = "freeze", "Muzlatish"

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="powerup_logs")
    attacker = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="attacks"
    )
    victim = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="victim_of")
    type = models.CharField(max_length=10, choices=Type.choices)
    points_amount = models.PositiveIntegerField(default=0)
    freeze_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Super-kuch jurnali"
        verbose_name_plural = "Super-kuchlar jurnali"
        ordering = ["-created_at"]
