# 🎯 Bilimdon

Maktab o'quvchilari uchun real vaqtda ishlaydigan, ko'chirishga qarshi himoyali onlayn test-o'yin platformasi (Kahoot uslubida).

**Texnologiyalar:** Python 3.12, Django 5, Django Channels + Daphne, Redis, PostgreSQL, Celery, Alpine.js, Tailwind CSS (CDN), Chart.js, openpyxl, qrcode.

## Mac'da o'rnatish

### 1. Dasturlar
```bash
# Python 3.12 va Redis (Homebrew)
brew install python@3.12 redis
brew services start redis        # yoki: redis-server
```
**PostgreSQL** — [Postgres.app](https://postgresapp.com) orqali o'rnatilgan va ishlab turgan bo'lishi kerak (port 5432). Baza `test_oyindb` yaratilgan bo'lishi kerak:
```bash
psql -U postgres -c "CREATE DATABASE test_oyindb;"   # agar hali yaratilmagan bo'lsa
```

### 2. Loyiha
```bash
cd test-o\'yin                       # loyiha papkasi
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                 # so'ng .env ichiga DB_PASSWORD ni yozing
python manage.py migrate
python manage.py createsuperuser     # o'qituvchi hisobi (yoki: python manage.py seed_demo)
```
`python manage.py seed_demo` — sinash uchun `ustoz / ustoz12345` o'qituvchisi, sinflar va 6 ta savol yaratadi.

> O'qituvchilarni `/admin/` orqali qo'shasiz (Foydalanuvchilar bo'limi).

## Ishga tushirish

Har birini alohida terminalda:

```bash
# 1) Veb-server (HTTP + WebSocket). Dasturlash uchun (statik fayllarni ham beradi):
python manage.py runserver 0.0.0.0:8000
#    yoki toza Daphne:
#    daphne -b 0.0.0.0 -p 8000 config.asgi:application   (statik fayllar uchun nginx/whitenoise kerak)

# 2) Celery worker (taymer tugaganda avtomatik topshirish, muzlatish tugashi)
celery -A config worker -l info
```

Brauzerda:
- O'qituvchi: <http://localhost:8000/accounts/login/> → `/panel/`
- O'quvchi: <http://localhost:8000/> yoki QR-kod orqali

Telefonlar ulanishi uchun kompyuter va telefon bitta Wi-Fi'da bo'lsin; QR-kod `http://<kompyuter-IP>:8000/kirish/<kod>/` manzilini beradi — o'qituvchi sahifasini ham shu IP orqali oching (`http://192.168.x.x:8000/panel/`), aks holda QR `localhost`ni ko'rsatadi. `.env` da `ALLOWED_HOSTS` ga shu IP yoki `*` kiriting.

### Redis'siz sinab ko'rish (faqat dasturlash)
`.env` ga `DEV_NO_REDIS=True` yozing: kanal qatlami xotirada ishlaydi, Celery vazifalari o'tkazib yuboriladi (taymer tugashi serverda "dangasa" tekshiriladi). Faqat **bitta** jarayon bilan ishlaydi.

## Ishlash tartibi
1. **Sinflar** bo'limida sinflarni qo'shing; **Savollar** bo'limida savollar yarating yoki Excel'dan import qiling (shablonni yuklab oling).
2. **Yangi xona**: savollarni tanlang, vaqt, parol va sozlamalarni kiriting. Xona 6 xonali raqam oladi, savollarning **nusxasi** saqlanadi.
3. **📺 Proyektor** tugmasi — QR-kod va xona raqamini katta ekranda ko'rsatadi.
4. O'quvchilar kiradi (ism, familiya, sinf, raqam, parol, avatar) → kutish xonasi.
5. **START** → o'quvchilarda "Testni boshlash" tugmasi chiqadi, bosganda to'liq ekranga o'tadi.
6. Pauza, +vaqt, qoidabuzarliklar, kech kirish so'rovlari, jonli reyting — hammasi xona boshqaruv sahifasida.
7. Yakunda podium, **Natijalarni ko'rishga ruxsat berish**, Excel eksport va statistika.

## Himoya va adolat qoidalari
- To'g'ri javoblar o'quvchi brauzeriga test tugamaguncha **yuborilmaydi**; ball, vaqt, super-kuchlar serverda hisoblanadi.
- Savollar va variantlar tartibi har bir o'quvchi uchun bir marta aralashtirilib bazada saqlanadi.
- Bir o'quvchi — bitta brauzer: session token `localStorage` + `HttpOnly` cookie'da; WebSocket ikkalasi mos kelgandagina ochiladi. Xuddi shu o'quvchining ikkinchi oynasi ochilsa, eskisi yopiladi.
- Fullscreen'dan chiqish, oyna/tab almashtirish, PrintScreen, DevTools — darhol chetlatish; internet uzilishi qoidabuzarlik emas. Javoblar `client_uuid` bilan idempotent.

## Testlar
```bash
pytest
```
Test sozlamalari (`config/test_settings.py`) Redis talab qilmaydi; PostgreSQL kerak (`test_` prefiksli vaqtinchalik baza yaratiladi).

## Cheklovlar
- **iPhone (iPhone Safari)** Fullscreen API'ni qo'llamaydi, shuning uchun test iPhone'da boshlanmaydi. Kompyuter, planshet yoki Android ishlating.
- Tailwind, Alpine, Chart.js va konfetti CDN orqali yuklanadi — maktabda internet bo'lishi kerak. Oflayn kerak bo'lsa, fayllarni `static/vendor/` ga yuklab, `templates/base.html` dagi havolalarni almashtiring.
- Brauzer tomonidagi himoya (Ctrl+C, F12, ...) to'liq kafolat bermaydi; asosiy himoya — serverdagi nazorat va qoidabuzarlik jurnali.
- Rasm bo'lsa, xona yaratilganda fayl `media/snapshots/` ga nusxalanadi.

## Dizayn tizimi
- **Tokenlar:** barcha ranglar `static/css/app.css` dagi `:root` CSS o'zgaruvchilarida (RGB kanallari), `templates/base.html` dagi Tailwind config'ga ulangan (`bg-brand`, `text-sun`, `bg-ok/20` ...). Tungi rejim `.dark` klassi bilan o'qituvchi panelida.
- **Shriftlar:** o'quvchi ekranlari — Baloo 2 / Nunito, o'qituvchi paneli — Inter (Google Fonts). Raqamlar `tabular-nums`.
- **Javob tugmalari:** ▲ qizil, ◆ ko'k, ● sariq, ■ yashil, ★ binafsha, ⬢ to'q sariq (rang + shakl).
- **Avatarlar:** 24 ta original SVG avatar `static/js/core.js` ichida generatsiya qilinadi (tashqi kutubxonasiz).
- **Kutubxonalar:** GSAP (count-up, uchish), canvas-confetti, Lucide ikonkalari, Chart.js, lottie-web (ixtiyoriy).
- **Ovozlar:** Web Audio API orqali sintez qilingan (`static/js/sound.js`), umumiy balandlik va o'chirish bilan. Howler.js ishlatilmaydi — ovoz fayllari yo'q.
- **Lottie:** `static/lottie/freeze.json`, `steal.json`, `win.json` fayllarini qo'ysangiz o'ynaydi (hozir CSS/GSAP animatsiyalari ishlaydi).
- `prefers-reduced-motion` yoqilgan bo'lsa animatsiyalar o'chiriladi/soddalashadi.
- Klaviatura: savol ekranida `1`–`6` tugmalari bilan javob berish mumkin.

## Excel import (fan, mavzu, savol, to'plam)
Bitta `.xlsx` fayl, 3 varaq: **Savollar**, **To'plamlar**, **To'plam savollari** (bo'sh shablon: panelda "Excel import" → "Shablonni yuklab olish").

```bash
python manage.py import_questions python_test_savollari.xlsx --subject "Python"
# ixtiyoriy: --teacher <username> --grade "8-sinf"
```
Takroriy importda mavjud mavzu, savol va to'plamlar qayta yaratilmaydi; xatoli qatorlar (qator raqami va sababi bilan) ko'rsatiladi, to'g'rilari saqlanadi.

## Savollar soni va taqsimot (to'plam generatori)
- Hajm **10–100** (slayder qadami 5, raqam maydoni, 10…100 tugmalari). Tanlangan mavzularda savol kam bo'lsa, testga bazadagi eng ko'pi tushadi va sahifa nechta mavzu kerakligini maslahat qiladi.
- Taqsimot usullari: teng (qoldiq tasodifiy mavzularga), proporsional, oxirgi mavzuga urg'u (40%), to'liq tasodifiy. Jami doim tanlangan songa aynan teng; mavzuda savol yetmasa ortgan qism boshqalarga o'tadi; hech bir mavzu 0 olmaydi (son mavzulardan kam bo'lgan holat bundan mustasno).
- Qo'lda [−]/[+] — farq qulflanmagan mavzulardan olinadi/qo'shiladi, o'zgargan mavzu 🔒 bo'ladi; «Avtomatikka qaytarish» qulflarni olib tashlaydi. Qo'lda sozlangan taqsimot to'plamda saqlanadi va «Qayta aralashtirish» da ham o'zgarmaydi.
- «Barcha to'plamlarni yaratish» zinapoyasiga «barcha mavzular → 100 ta» qo'shilgan. Xona yaratishda vaqt tavsiyasi: har savolga ~30 soniya.
