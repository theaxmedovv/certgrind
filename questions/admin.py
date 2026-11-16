from django.contrib import admin

from .models import (
    Question, QuestionOption, QuestionSet, QuestionSetItem, SchoolClass, Subject, Topic,
)


class OptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "topic", "difficulty", "external_no", "teacher", "created_at")
    list_filter = ("topic", "difficulty", "teacher")
    search_fields = ("text", "code")
    inlines = [OptionInline]


class SetItemInline(admin.TabularInline):
    model = QuestionSetItem
    extra = 0
    raw_id_fields = ("question",)


@admin.register(QuestionSet)
class QuestionSetAdmin(admin.ModelAdmin):
    list_display = ("name", "set_type", "size", "subject", "teacher", "last_used_at")
    list_filter = ("set_type", "subject")
    search_fields = ("name",)
    inlines = [SetItemInline]


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "order", "teacher")
    list_filter = ("subject",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "grade", "teacher")


admin.site.register(SchoolClass)
admin.site.register(QuestionOption)
