from django.conf import settings
from django.db import models


class PcepModule(models.Model):
    number = models.PositiveSmallIntegerField("Modul raqami", unique=True)
    title = models.CharField("Nomi", max_length=200)
    exam_weight = models.PositiveSmallIntegerField("Imtihondagi ulushi (%)")

    class Meta:
        ordering = ["number"]
        verbose_name = "PCEP moduli"
        verbose_name_plural = "PCEP modullari"

    def __str__(self):
        return f"{self.number}-modul · {self.title}"


class PcepQuestion(models.Model):
    BANK_MODULE, BANK_PRACTICE, BANK_FINAL = "module", "practice", "final"
    BANKS = [(BANK_MODULE, "Modul testi"), (BANK_PRACTICE, "Practice Test"), (BANK_FINAL, "Final Practice Test")]
    SINGLE, MULTIPLE = "single", "multiple"
    MATCH, ORDER, CATEGORIZE, CODE_GAP = "match", "order", "categorize", "code_gap"
    TYPES = [(SINGLE, "Bitta javob"), (MULTIPLE, "Bir nechta javob"), (MATCH, "Moslashtirish"),
             (ORDER, "Tartiblash"), (CATEGORIZE, "Guruhlash"), (CODE_GAP, "Kodga joylash")]
    INTERACTIVE = (MATCH, ORDER, CATEGORIZE, CODE_GAP)

    bank = models.CharField("Bo'lim", max_length=10, choices=BANKS, default=BANK_MODULE, db_index=True)
    module = models.ForeignKey(PcepModule, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    section = models.CharField("PCEP bo'limi", max_length=10, blank=True)
    text = models.TextField("Savol matni")
    code = models.TextField("Kod", blank=True)
    image = models.ImageField("Rasm", upload_to="pcep/", blank=True)
    question_type = models.CharField(max_length=12, choices=TYPES, default=SINGLE)
    interaction = models.JSONField("Interaktiv ma'lumot", default=dict, blank=True)
    source_file = models.CharField("Manba fayli", max_length=300, blank=True)
    source_ref = models.CharField("Manbadagi raqam", max_length=40, blank=True)
    converted_from = models.CharField("Asl tur", max_length=30, blank=True, help_text="Masalan: drag_drop, fill_gaps")
    explanation_uz = models.JSONField("Tushuntirish (UZ)", default=dict, blank=True)
    explanation_en = models.TextField("Asl izoh (EN)", blank=True)
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    verified = models.BooleanField("Matn tekshirilgan", default=False)
    needs_review = models.BooleanField("Tekshirish kerak", default=False)
    review_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["bank", "module__number", "source_ref"]
        verbose_name = "PCEP savoli"
        verbose_name_plural = "PCEP savollari"

    def __str__(self):
        return f"[{self.bank} {self.source_ref}] {self.text[:60]}"


class PcepOption(models.Model):
    question = models.ForeignKey(PcepQuestion, on_delete=models.CASCADE, related_name="options")
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text[:60]


class PcepAttempt(models.Model):
    MODES = [("module", "Modul testi"), ("mixed", "Aralash test"), ("exam", "Imtihon rejimi"),
             ("mistakes", "Xatolar ustida"), ("practice", "Practice Test"), ("final", "Final Practice Test")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="pcep_attempts")
    mode = models.CharField(max_length=10, choices=MODES)
    module = models.ForeignKey(PcepModule, null=True, blank=True, on_delete=models.SET_NULL)
    total = models.PositiveSmallIntegerField(default=0)
    correct = models.PositiveSmallIntegerField(default=0)
    percent = models.FloatField(default=0)
    duration_seconds = models.PositiveIntegerField(default=0)
    timed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class PcepAttemptAnswer(models.Model):
    attempt = models.ForeignKey(PcepAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(PcepQuestion, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)
    option_order = models.JSONField(default=list, blank=True)
    selected_option_ids = models.JSONField(default=list, blank=True)
    response = models.JSONField(default=dict, blank=True)  # interaktiv savollar uchun javob
    is_correct = models.BooleanField(default=False)
    flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]
