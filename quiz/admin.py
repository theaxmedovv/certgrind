from django.contrib import admin

from .models import (
    Answer,
    Participant,
    ParticipantQuestion,
    PowerUpCode,
    PowerUpLog,
    Violation,
)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "school_class", "room", "status", "score", "is_late")
    list_filter = ("status", "is_late", "room")
    search_fields = ("first_name", "last_name")


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("participant", "room_question", "is_correct", "points", "response_ms")
    list_filter = ("is_correct",)


@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ("participant", "type", "occurred_at", "decision")
    list_filter = ("type", "decision")


admin.site.register(ParticipantQuestion)
admin.site.register(PowerUpCode)
admin.site.register(PowerUpLog)
