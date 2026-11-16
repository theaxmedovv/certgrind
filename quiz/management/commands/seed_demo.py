from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from questions.services import get_topic
from questions.models import Question, QuestionOption, SchoolClass, Topic

DEMO = [
    ("Sikllar", "Python'da qaysi operator sikl yaratadi?", ["for", "if", "def", "import"], 0),
    ("Sikllar", "range(3) qanday qiymatlar beradi?", ["1,2,3", "0,1,2", "0,1,2,3", "1,2"], 1),
    ("Massivlar", "Ro'yxatga element qo'shish metodi?", ["add()", "append()", "push()", "insert_end()"], 1),
    ("Massivlar", "len([1,2,3]) nimaga teng?", ["2", "3", "4", "0"], 1),
    ("Arifmetika", "7 // 2 nimaga teng?", ["3.5", "3", "4", "2"], 1),
    ("Arifmetika", "2 ** 3 nimaga teng?", ["6", "5", "8", "9"], 2),
]


class Command(BaseCommand):
    help = "Sinash uchun demo o'qituvchi (ustoz/ustoz12345), sinflar va savollar yaratadi"

    def handle(self, *args, **opts):
        user, created = User.objects.get_or_create(username="ustoz", defaults={"is_staff": True})
        if created:
            user.set_password("ustoz12345")
            user.save()
        for n in ("5-A", "5-B", "7-A", "7-B"):
            SchoolClass.objects.get_or_create(name=n)
        if not Question.objects.filter(teacher=user).exists():
            for topic, text, options, correct in DEMO:
                t = get_topic(user, topic)
                q = Question.objects.create(teacher=user, topic=t, text=text)
                for i, o in enumerate(options):
                    QuestionOption.objects.create(question=q, text=o, is_correct=(i == correct))
        self.stdout.write(self.style.SUCCESS("Tayyor. Login: ustoz / ustoz12345"))
