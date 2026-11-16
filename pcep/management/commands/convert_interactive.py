"""Interaktiv savollarni (moslashtirish, tartiblash, guruhlash, kodga joylash) bazaga qo'llaydi.

Manba: pcep/data/interactive.json. Avval oddiy test varianti sifatida import qilingan
savollar topiladi va haqiqiy interaktiv savolga aylantiriladi (PcepOption'lar o'chiriladi).
Har bir savol uchun tekshiruv ishga tushiriladi va hisobot chiqariladi.
"""
import json
import keyword
import os
import re
import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from pcep.management.commands.import_pcep import fingerprint
from pcep.models import PcepQuestion

DATA = Path(__file__).resolve().parents[2] / "data" / "interactive.json"
PRECEDENCE = {"EXPONENTIATION": 4, "MULTIPLICATION": 3, "DIVISION": 3, "ADDITION": 2, "SUBTRACTION": 2}
TYPE_NAMES = {str: "String", bool: "Boolean", int: "Integer", float: "Float"}


def _strip(s):
    return re.sub(r"\s+", "", s)


def fill_template(ix, mapping):
    """Shablondagi {{gN}} larni blok matnlari bilan to'ldiradi (mapping: slot -> block id)."""
    by = {b["id"]: b["text"] for b in ix["blocks"]}
    return re.sub(r"\{\{(g\d+)\}\}", lambda m: by.get(mapping.get(m.group(1)), "?"), ix["template"])


def run_python(code):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code], capture_output=True, timeout=5, env=env, input=b"")
    out = r.stdout.decode("utf-8", "replace").replace(chr(13) + chr(10), chr(10)).strip()
    return r.returncode, out, r.stderr.decode("utf-8", "replace").strip()


def verify_item(item):
    """(ok: bool, izoh: str)"""
    ix, v, t = item["interaction"], item.get("verify", {}), item["type"]
    try:
        if t == "match":
            names = {b["id"]: b["text"] for b in ix["items"]}
            for tg in ix["targets"]:
                real = TYPE_NAMES[type(eval(tg["text"], {}, {}))]
                if names[ix["answer"][tg["id"]]] != real:
                    return False, f"{tg['text']} haqiqatda {real}"
            return True, "turlar Python'da eval qilib tekshirildi"
        if t == "order":
            txt = {i["id"]: i["text"] for i in ix["items"]}
            pr = [PRECEDENCE[txt[i]] for i in ix["answer"]]
            return pr == sorted(pr, reverse=True), "ustuvorlik jadvali bilan solishtirildi"
        if t == "categorize":
            txt = {i["id"]: i["text"] for i in ix["items"]}
            for iid, cat in ix["answer"].items():
                legal = txt[iid].isidentifier() and not keyword.iskeyword(txt[iid])
                if legal != (cat == "c1"):
                    return False, f"{txt[iid]} noto'g'ri guruhda"
            return True, "isidentifier()/keyword bilan tekshirildi"
        if t == "code_gap":
            filled = fill_template(ix, ix["answer"])
            if _strip(filled) != _strip(ix["solution"]):
                return False, "bloklar yig'indisi 'solution' ga mos emas"
            blocks_used = list(ix["answer"].values())
            if len(set(blocks_used)) != len(blocks_used):
                return False, "bitta blok ikki katakka qo'yilgan"
            for alt in ix.get("alternatives", []):
                if _strip(fill_template(ix, alt)) != _strip(ix["solution"]):
                    return False, "alternativ javob mos emas"
            code = v.get("setup", "") + ix["solution"] + v.get("suffix", "")
            if "expect" in v:
                rc, out, err = run_python(code)
                if rc:
                    return False, "kod xato bilan to'xtadi: " + (err.splitlines() or ["?"])[-1]
                return out == v["expect"], f"natija: {out!r}" + ("" if out == v["expect"] else f" (kutilgan {v['expect']!r})")
            compile(code, "<pcep>", "exec")
            return True, "sintaksis tekshirildi (input() bor, ishga tushirilmadi)"
    except Exception as e:  # noqa: BLE001
        return False, f"tekshiruv xatosi: {e}"
    return False, "noma'lum tur"


def count_slots(item):
    ix = item["interaction"]
    t = item["type"]
    if t == "match":
        return len(ix["targets"])
    if t == "order":
        return len(ix["items"])
    if t == "categorize":
        return len([i for i in ix["items"] if i["id"] not in ix.get("prefilled", {})])
    return len(ix["answer"])


def count_blocks(item):
    ix = item["interaction"]
    return len(ix.get("blocks") or ix.get("items") or [])


class Command(BaseCommand):
    help = "Interaktiv savollarni (interactive.json) bazaga qo'llaydi va tekshiradi"

    @transaction.atomic
    def handle(self, *args, **opts):
        if not DATA.exists():
            self.stdout.write("interactive.json topilmadi — o'tkazib yuborildi.")
            return
        items = json.loads(DATA.read_text(encoding="utf-8"))
        rows, applied, missing = [], 0, []
        for it in items:
            ok, note = verify_item(it)
            qs = PcepQuestion.objects.filter(bank=it["bank"], source_ref=it["ref"])
            if it["bank"] == "module":
                qs = qs.filter(module__number=it["module"])
            main = qs.first()
            if not main:
                missing.append(f"{it['bank']}:{it['module'] or '-'}#{it['ref']}")
                continue
            targets = [main]
            if it["bank"] == "module":
                if main.question_type not in PcepQuestion.INTERACTIVE:  # hali aylantirilmagan: eski matn bo'yicha nusxalar
                    targets += list(PcepQuestion.objects.filter(bank="practice").filter(
                        text=main.text, code=main.code).exclude(id=main.id))
                core = {k: v for k, v in it["interaction"].items() if k != "result"}
                have = {t.id for t in targets}
                for q2 in PcepQuestion.objects.filter(bank="practice", question_type=it["type"]).exclude(id__in=have):
                    if {k: v for k, v in q2.interaction.items() if k != "result"} == core:
                        targets.append(q2)
            for q in targets:
                self._apply(q, it, ok)
                applied += 1
            rows.append((it, ok, note, len(targets)))
        self._report(rows, applied, missing)

    def _apply(self, q, it, ok):
        q.options.all().delete()
        q.question_type = it["type"]
        q.text = it["text"]
        q.code = ""
        q.interaction = it["interaction"]
        q.explanation_uz = it["explanation_uz"]
        q.converted_from = ""
        q.verified = bool(ok)
        q.needs_review = not ok
        q.review_note = "" if ok else "qo'lda tekshirish kerak"
        if it.get("section"):
            q.section = it["section"]
        q.fingerprint = fingerprint(q.bank, q.text, json.dumps(q.interaction, sort_keys=True, ensure_ascii=False))
        q.save()

    def _report(self, rows, applied, missing):
        w = self.stdout.write
        w("\nINTERAKTIV SAVOLLAR HISOBOTI")
        w(f"{'savol':<22}{'tur':<11}{'bloklar':>8}{'kataklar':>9}  {'nusxa':>5}  tekshiruv")
        bad = 0
        for it, ok, note, n in rows:
            ref = f"{it['bank']}:{it['module'] or '-'}#{it['ref']}"
            mark = "✓" if ok else "qo'lda tekshirish kerak"
            bad += 0 if ok else 1
            w(f"{ref:<22}{it['type']:<11}{count_blocks(it):>8}{count_slots(it):>9}  {n:>5}  {mark} — {note}")
        w(f"\nJami: {len(rows)} noyob savol, {applied} ta yozuv yangilandi (nusxalari bilan). Qo'lda tekshirish kerak: {bad}")
        if missing:
            w("Bazada topilmadi: " + ", ".join(missing))
