from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from questions import services


class Command(BaseCommand):
    help = "Excel fayldan (Savollar / To'plamlar / To'plam savollari) fan, mavzu, savol va to'plamlarni yuklaydi"

    def add_arguments(self, parser):
        parser.add_argument("path", help="python_test_savollari.xlsx")
        parser.add_argument("--subject", default="Python", help="Fan nomi")
        parser.add_argument("--grade", default="", help="Sinf darajasi")
        parser.add_argument("--teacher", default=None, help="O'qituvchi username (standart: birinchi superuser)")

    def handle(self, *args, **opts):
        User = get_user_model()
        if opts["teacher"]:
            teacher = User.objects.filter(username=opts["teacher"]).first()
        else:
            teacher = User.objects.filter(is_superuser=True).order_by("id").first() or User.objects.order_by("id").first()
        if teacher is None:
            raise CommandError("O'qituvchi topilmadi. Avval createsuperuser yoki --teacher bering.")
        try:
            f = open(opts["path"], "rb")
        except OSError as e:
            raise CommandError(f"Faylni ochib bo'lmadi: {e}")
        with f:
            rep = services.import_workbook(f, teacher, subject_name=opts["subject"], grade=opts["grade"])
        if rep["file_error"]:
            raise CommandError(rep["file_error"])
        self.stdout.write(self.style.SUCCESS(
            f"Fan '{rep['subject']}' (o'qituvchi: {teacher.username}): "
            f"{rep['topics_created']} mavzu, {rep['questions_created']} savol yangi "
            f"({rep['questions_existing']} ta avvaldan bor), "
            f"{rep['sets_created']} to'plam yangi ({rep['sets_existing']} ta avvaldan bor)."
        ))
        for e in rep["errors"]:
            self.stdout.write(self.style.WARNING(f"  [{e['sheet']}] {e['row']}-qator: {e['reason']}"))
        if rep["errors"]:
            self.stdout.write(self.style.WARNING(f"Jami {len(rep['errors'])} ta xato (qolganlari saqlandi)."))
