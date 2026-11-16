from django.contrib import admin

from .models import Room, RoomEvent, RoomQuestion


class RoomQuestionInline(admin.TabularInline):
    model = RoomQuestion
    extra = 0
    readonly_fields = ("snapshot",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "teacher", "status", "created_at")
    list_filter = ("status", "teacher")
    search_fields = ("name", "code")
    exclude = ("password",)
    inlines = [RoomQuestionInline]


admin.site.register(RoomQuestion)
admin.site.register(RoomEvent)
