from django.conf import settings
from django.db import models


def default_difficulty_mix():
    return {"easy": 30, "medium": 50, "hard": 20}


class SchoolClass(models.Model):
    name = models.CharField("Sinf nomi", max_length=20, unique=True)

    class Meta:
        verbose_name = "Sinf"
        verbose_name_plural = "Sinflar"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Subject(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subjects"
    )
    name = models.CharField("Fan", max_length=120)
    grade = models.CharField("Sinf darajasi", max_length=30, blank=True)

    class Meta:
        verbose_name = "Fan"
        verbose_name_plural = "Fanlar"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["teacher", "name"], name="uniq_subject_per_teacher")
        ]

    def __str__(self):
        return self.name


class Topic(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topics"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="topics", null=True, blank=True,
        verbose_name="Fan",
    )
    name = models.CharField("Mavzu", max_length=120)
    order = models.PositiveIntegerField("Tartib raqami", default=0)

    class Meta:
        verbose_name = "Mavzu"
        verbose_name_plural = "Mavzular"
        ordering = ["subject", "order", "name"]
        indexes = [models.Index(fields=["subject", "order"], name="topic_subject_order_idx")]
        constraints = [
            models.UniqueConstraint(fields=["subject", "name"], name="uniq_topic_per_subject")
        ]

    def __str__(self):
        return self.name


class Question(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "easy", "Oson"
        MEDIUM = "medium", "O'rta"
        HARD = "hard", "Qiyin"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="questions"
    )
    topic = models.ForeignKey(
        Topic, on_delete=models.PROTECT, related_name="questions", verbose_name="Mavzu"
    )
    text = models.TextField("Savol matni")
    code = models.TextField("Kod bloki", blank=True)
    input_values = models.CharField("Kiritiladigan qiymatlar (input)", max_length=300, blank=True)
    external_no = models.PositiveIntegerField("Excel'dagi №", null=True, blank=True)
    image = models.ImageField("Rasm", upload_to="questions/", blank=True, null=True)
    difficulty = models.CharField(
        "Qiyinlik", max_length=10, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Savol"
        verbose_name_plural = "Savollar"
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:60]


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField("Variant", max_length=500)
    is_correct = models.BooleanField("To'g'ri", default=False)

    class Meta:
        verbose_name = "Javob varianti"
        verbose_name_plural = "Javob variantlari"
        ordering = ["id"]

    def __str__(self):
        return self.text[:60]


class QuestionSet(models.Model):
    class Type(models.TextChoices):
        TOPIC = "topic", "📘 Mavzu"
        CUMULATIVE = "cumulative", "📚 Yig'ma"
        MIXED = "mixed", "🎲 Aralash"

    class Distribution(models.TextChoices):
        EQUAL = "equal", "Teng"
        PROPORTIONAL = "proportional", "Savollar soniga proporsional"
        LATEST_FOCUS = "latest_focus", "Oxirgi mavzuga urg'u"
        RANDOM = "random", "To'liq tasodifiy"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="question_sets"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="question_sets", null=True, blank=True
    )
    name = models.CharField("Nomi", max_length=200)
    set_type = models.CharField(max_length=12, choices=Type.choices, default=Type.TOPIC)
    size = models.PositiveSmallIntegerField("Hajmi", default=15)
    topics = models.ManyToManyField(Topic, blank=True, related_name="question_sets")
    distribution = models.CharField(
        max_length=14, choices=Distribution.choices, default=Distribution.EQUAL
    )
    difficulty_mix = models.JSONField(default=default_difficulty_mix)
    allocation = models.JSONField("Mavzular bo'yicha taqsimot", null=True, blank=True)
    external_no = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "To'plam"
        verbose_name_plural = "To'plamlar"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class QuestionSetItem(models.Model):
    question_set = models.ForeignKey(QuestionSet, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="set_items")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "To'plam savoli"
        verbose_name_plural = "To'plam savollari"
        ordering = ["question_set", "order"]
        constraints = [
            models.UniqueConstraint(fields=["question_set", "question"], name="uniq_set_question")
        ]
