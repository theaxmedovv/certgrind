from django.contrib import admin

from .models import PcepAttempt, PcepModule, PcepOption, PcepQuestion


class OptionInline(admin.TabularInline):
    model = PcepOption
    extra = 0


@admin.register(PcepQuestion)
class PcepQuestionAdmin(admin.ModelAdmin):
    list_display = ("source_ref", "bank", "module", "section", "question_type", "verified", "needs_review")
    list_filter = ("bank", "module", "question_type", "verified", "needs_review")
    search_fields = ("text", "code")
    inlines = [OptionInline]


admin.site.register(PcepModule)
admin.site.register(PcepAttempt)
