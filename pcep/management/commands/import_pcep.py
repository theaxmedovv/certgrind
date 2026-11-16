"""PCEP savollarini JSON fayllardan yuklash.

Manba (dark-teal-coder/gitbook-PCEP-30-02-practice-test-compendium, MIT, (c) 2022 OpenEDG)
faqat skrinshotlardan iborat, shuning uchun savollar rasmlardan ko'chirib yozilgan va
`pcep/data/*.json` fayllarida turadi. Bu buyruq shu fayllarni bazaga yuklaydi.

    python manage.py import_pcep pcep/data
"""
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pcep.models import PcepModule, PcepOption, PcepQuestion

MODULES = [
    (1, "Computer Programming and Python Fundamentals", 18),
    (2, "Control Flow: Conditional Blocks and Loops", 29),
    (3, "Data Collections: Tuples, Dictionaries, Lists, and Strings", 25),
    (4, "Functions and Exceptions", 28),
]
SUPPORTED_TYPES = {"single", "multiple"}


def normalize(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def fingerprint(bank, text, code):
    """Takror tekshiruvi bo'lim (bank) ichida: Practice Test modul savollarini qayta ishlatishi mumkin."""
    return hashlib.sha256((bank + "|" + normalize(text) + "\n" + "\n".join(l.rstrip() for l in (code or "").strip().splitlines())).encode()).hexdigest()


def ensure_modules():
    return {n: PcepModule.objects.update_or_create(number=n, defaults={"title": t, "exam_weight": w})[0] for n, t, w in MODULES}


def parse_item(item):
    """Bitta JSON yozuvini tekshiradi; xato bo'lsa ValueError ko'taradi."""
    if item.get("unsupported"):
        raise ValueError(f"qo'llab-quvvatlanmaydi: {item.get('unsupported')}")
    if not normalize(item.get("text")):
        raise ValueError("savol matni bo'sh")
    opts = item.get("options") or []
    if len(opts) < 2:
        raise ValueError("variantlar 2 tadan kam")
    n_correct = sum(1 for o in opts if o.get("correct"))
    if n_correct == 0:
        raise ValueError("to'g'ri javob belgilanmagan")
    qtype = item.get("type") or ("multiple" if n_correct > 1 else "single")
    if qtype not in SUPPORTED_TYPES:
        raise ValueError(f"qo'llab-quvvatlanmaydi: tur {qtype}")
    if qtype == "single" and n_correct != 1:
        raise ValueError("single savolda to'g'ri javob soni 1 emas")
    if qtype == "multiple" and n_correct < 2:
        raise ValueError("multiple savolda to'g'ri javoblar 2 tadan kam")
    return qtype


class Command(BaseCommand):
    help = "PCEP savollarini JSON fayllardan yuklaydi (takrorlar o'tkazib yuboriladi)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON fayllar papkasi (yoki bitta .json fayl)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        base = Path(opts["path"])
        files = [base] if base.is_file() else sorted(f for f in base.glob("*.json") if f.name != "interactive.json")
        if not files:
            raise CommandError(f"{base} da .json fayl topilmadi")
        mods = ensure_modules()
        created, dup, errors, review = Counter(), Counter(), [], []
        seen = set(PcepQuestion.objects.values_list("fingerprint", flat=True))
        by_bank = defaultdict(Counter)

        with transaction.atomic():
            for f in files:
                data = json.loads(f.read_text(encoding="utf-8"))
                for item in data:
                    ref = f"{item.get('bank', 'module')}:{item.get('module') or '-'}#{item.get('num')}"
                    key = (item.get("bank", "module"), item.get("module") or 0)
                    try:
                        qtype = parse_item(item)
                        fp = fingerprint(item.get("bank", "module"), item["text"], item.get("code", ""))
                        bank_ = item.get("bank", "module")
                        same_ref = PcepQuestion.objects.filter(bank=bank_, source_ref=str(item.get("num", "")))
                        if bank_ == "module":
                            same_ref = same_ref.filter(module__number=item.get("module"))
                        # fingerprint yoki (bank, modul, raqam) bo'yicha allaqachon bor — shu jumladan
                        # interaktivga aylantirilgan savollar qayta oddiy test bo'lib kirmasin
                        if fp in seen or same_ref.exists():
                            dup[key] += 1
                            continue
                        seen.add(fp)
                        if opts["dry_run"]:
                            created[key] += 1
                            continue
                        q = PcepQuestion(
                            bank=item.get("bank", "module"),
                            module=mods.get(item.get("module") or (int(item["section"].split(".")[0]) if item.get("section") else None)),
                            section=item.get("section", ""),
                            text=item["text"].strip(),
                            code=(item.get("code") or "").strip("\n"),
                            question_type=qtype,
                            source_file=item.get("source_file", ""),
                            source_ref=str(item.get("num", "")),
                            converted_from=item.get("converted_from", ""),
                            explanation_en=item.get("explanation_en", ""),
                            fingerprint=fp,
                            verified=False,
                            needs_review=bool(item.get("needs_review")),
                            review_note=item.get("note", "")[:300],
                        )
                        img = item.get("image")
                        if img and (f.parent / img).exists():
                            dest = Path(settings.MEDIA_ROOT) / "pcep" / Path(img).name
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(f.parent / img, dest)
                            q.image.name = f"pcep/{Path(img).name}"
                        q.save()
                        PcepOption.objects.bulk_create(
                            [PcepOption(question=q, text=o["text"], is_correct=bool(o.get("correct")), order=i)
                             for i, o in enumerate(item["options"])]
                        )
                        created[key] += 1
                        if q.needs_review or q.converted_from:
                            review.append((ref, q.review_note or f"asl tur: {q.converted_from}"))
                    except (ValueError, KeyError) as e:
                        errors.append((ref, str(e)))

        self.stdout.write(self.style.SUCCESS("\nIMPORT HISOBOTI"))
        for bank in ("module", "practice", "final"):
            keys = sorted(k for k in set(created) | set(dup) if k[0] == bank)
            for k in keys:
                label = f"{k[1]}-modul" if bank == "module" else f"{bank} (modul {k[1] or '-'})"
                self.stdout.write(f"  {label:28} yuklandi: {created[k]:3}  takror: {dup[k]}")
        self.stdout.write(f"  JAMI yuklandi: {sum(created.values())}, takror: {sum(dup.values())}, xato: {len(errors)}")
        if errors:
            self.stdout.write(self.style.ERROR("Xatolar:"))
            for ref, why in errors:
                self.stdout.write(f"  {ref}: {why}")
        if review:
            self.stdout.write(self.style.WARNING(f"Tekshirilmagan / aylantirilgan savollar: {len(review)}"))
            for ref, why in review:
                self.stdout.write(f"  {ref}: {why}")

        if not opts["dry_run"]:
            from django.core.management import call_command
            call_command("convert_interactive")
