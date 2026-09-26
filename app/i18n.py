from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("fa", "en", "de")

LANGUAGE_BUTTONS = {
    "fa": "🇮🇷 فارسی",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
}

MENU_LABELS = {
    "fa": {
        "new": "🎬 ضبط جلسه جدید",
        "premium": "✨ پلن ویژه",
        "now": "⚡ ورود فوری",
        "help": "❓ راهنما",
        "language": "🌐 زبان",
        "admin": "⚙️ پنل مدیریت",
        "placeholder": "لینک Google Meet رو بفرست…",
    },
    "en": {
        "new": "🎬 New recording",
        "premium": "✨ Premium",
        "now": "⚡ Join now",
        "help": "❓ Help",
        "language": "🌐 Language",
        "admin": "⚙️ Admin panel",
        "placeholder": "Send a Google Meet link…",
    },
    "de": {
        "new": "🎬 Neue Aufnahme",
        "premium": "✨ Premium",
        "now": "⚡ Sofort beitreten",
        "help": "❓ Hilfe",
        "language": "🌐 Sprache",
        "admin": "⚙️ Adminbereich",
        "placeholder": "Google Meet Link senden…",
    },
}

MESSAGES: dict[str, dict[str, str]] = {
    "fa": {
        "language_choose": "🌐 زبان ربات رو انتخاب کن. زبان جلسه مستقل از این تنظیمه و به صورت خودکار تشخیص داده می‌شه.",
        "language_changed": "✅ زبان ربات روی فارسی تنظیم شد.",
        "new_prompt": "لینک Google Meet رو همینجا بفرست. اگه جلسه توی کلندر باشه سر وقت وارد می‌شم؛ اگه همین الان شروع شده از «⚡ ورود فوری» استفاده کن.",
        "admin_ready": "پنل مدیریت آماده‌ست 👇\n{url}\n\nاین لینک ۱۵ دقیقه اعتبار داره.",
        "admin_only": "این بخش فقط برای مدیر رباته 🙂",
        "premium_active": "✨ پلن ویژه‌ت فعاله تا {until}.\n\nقابلیت‌های ویژه:\n• کیفیت بالاتر ضبط\n• فایل صوتی جداگانه\n• متن جلسه با تشخیص خودکار زبان\n• پیش نویس صورتجلسه\n• ظرفیت اختصاصی و اولویت ورود",
        "premium_offer": "✨ پلن ویژه BeOnMeet\n\nقابلیت‌ها:\n• کیفیت بالاتر ضبط\n• فایل صوتی جداگانه\n• متن جلسه با تشخیص خودکار زبان\n• پیش نویس صورتجلسه\n• ظرفیت اختصاصی و اولویت ورود\n\nیکی از پلن‌ها رو انتخاب کن:",
        "plan_monthly": "۱ ماهه · ۱۹۸ هزار تومان",
        "plan_quarterly": "۳ ماهه · ۴۹۹ هزار تومان",
        "plan_halfyear": "۶ ماهه · ۷۹۹ هزار تومان",
        "calendar_connected": "✅ کلندر وصله",
        "calendar_disconnected": "⚠️ کلندر هنوز وصل نیست\n{url}",
        "start": "سلام 👋 من BeOnMeet هستم.\n\nلینک Google Meet رو برام بفرست. فقط یادت باشه {bot_email} رو هم به همون ایونت کلندر دعوت کنی. سر وقت وارد جلسه می‌شم، ضبطش می‌کنم و آخرش فایل رو همینجا برات می‌فرستم.\n\nزبان جلسه مهم نیست؛ متن جلسه چندزبانه است و زبان رو خودکار تشخیص می‌دم.\n\n{auth_status}",
        "now_prompt": "باشه. حالا لینک Google Meet رو بفرست تا همین الان واردش بشم.",
        "calendar_error": "⚠️ درخواستت ذخیره شد ولی الان نتونستم کلندر گوگل رو بخونم. کمی بعد دوباره لینک رو بفرست.",
        "event_found": "✅ گرفتمش. ایونت کلندر هم پیدا شد.\n{meet_url}\n🕒 {when}",
        "event_missing": "⚠️ لینکت رو ذخیره کردم، ولی هنوز این جلسه رو توی کلندر {bot_email} نمی‌بینم.\n\nاول {bot_email} رو به ایونت دعوت کن. اگر قبلاً دعوتش کردی، تنظیم «Add invitations to my calendar» رو روی «From everyone» بذار یا دعوت فعلی رو قبول کن. بعد لینک رو دوباره بفرست.\n\nاگر جلسه همین الان شروع شده:\n/now {meet_url}",
        "send_link": "یه لینک Google Meet برام بفرست، مثلاً:\nhttps://meet.google.com/abc-defg-hij",
        "queue_premium": "⚡ ظرفیت ویژه و ظرفیت اضافه فعلاً پرن. درخواستت با اولویت ویژه ثبت شد و نفر {position} صف ویژه‌ای. به محض آزاد شدن اولین ورکر وارد می‌شم.",
        "queue_free": "⏳ رکوردرهای رایگان الان پرن. درخواستت ثبت شد و نفر {position} صفی. به محض آزاد شدن ظرفیت خودکار وارد جلسه می‌شم.",
        "launch_premium": "⚡ ورکر اختصاصی پلن ویژه رزرو شد. دارم وارد جلسه می‌شم…\n{meet_url}",
        "launch_priority": "⚡ با اولویت ویژه از ظرفیت آزاد دارم وارد جلسه می‌شم…\n{meet_url}",
        "launch_free": "⏳ درخواست ورود ارسال شد. دارم وارد جلسه می‌شم…\n{meet_url}",
        "dispatch_retry": "⚠️ فعلاً نتونستم درخواست ورود رو به رکوردر برسونم. خودکار دوباره امتحان می‌کنم.\n{meet_url}",
        "queue_expired": "⌛ نوبت رکوردر قبل از پایان جلسه آزاد نشد و درخواست از صف خارج شد.",
        "premium_ready": "⚡ ظرفیت ویژه آزاد شد و الان دارم وارد جلسه می‌شم…\n{meet_url}",
        "queue_ready": "✅ نوبتت از صف رسید. الان دارم وارد جلسه می‌شم…\n{meet_url}",
        "waiting_admission": "🚪 رسیدم پشت در جلسه. Google Meet از میزبان می‌خواد منو Admit کنه. به محض ورود، ضبط خودکار شروع می‌شه.",
        "recording_started": "🎥 وارد جلسه شدم و ضبط شروع شد.",
        "recording_ready_caption": "🎥 ضبط جلسه‌ت آماده‌ست",
        "recording_finished": "✅ جلسه تموم شد. دارم فایل ضبط شده رو برات می‌فرستم…",
        "audio_ready_caption": "🎧 فایل صوتی جداگانه جلسه‌ت آماده‌ست",
        "transcribing": "📝 دارم متن جلسه رو با تشخیص خودکار زبان آماده می‌کنم. برای جلسه‌های طولانی ممکنه کمی زمان ببره…",
        "transcript_header": "متن خودکار جلسه BeOnMeet",
        "transcript_warning": "توجه: این متن به صورت خودکار ساخته شده و ممکنه خطا داشته باشه.",
        "transcript_detected": "زبان‌های تشخیص داده شده: {languages}",
        "transcript_ready_caption": "📝 متن جلسه آماده‌ست. متن زبان اصلی جلسه حفظ شده و ترجمه نشده.",
        "transcript_empty": "📝 از این جلسه متن قابل استفاده‌ای درنیومد. احتمالاً صدا خیلی کم یا نامفهوم بوده.",
        "transcript_error": "⚠️ فایل صوتی آماده شد ولی تبدیلش به متن این بار خطا خورد. ویدیو و صوتت سر جاشه.",
        "delivery_error": "⚠️ ضبط تموم شده ولی ارسالش به تلگرام خطا خورد. فایل فعلاً در حافظه موقت نگه داشته شده.",
        "large_video": "حجم ویدیو زیاده، برای همین توی {count} قسمت قابل پخش می‌فرستم.",
        "video_part": "قسمت {index} از {count}",
        "payment_confirmed": "✨ پرداختت تأیید شد و پلن ویژه فعال شد.\nتا {until} فعاله.",
    },
    "en": {
        "language_choose": "🌐 Choose the bot language. Meeting language is independent and detected automatically.",
        "language_changed": "✅ Bot language changed to English.",
        "new_prompt": "Send the Google Meet link here. If it is on the calendar, I’ll join on time. If it has already started, use “⚡ Join now”.",
        "admin_ready": "The admin panel is ready 👇\n{url}\n\nThis link is valid for 15 minutes.",
        "admin_only": "This section is only available to the bot administrator 🙂",
        "premium_active": "✨ Your Premium plan is active until {until}.\n\nPremium features:\n• Higher recording quality\n• Separate audio file\n• Multilingual transcript with automatic language detection\n• Meeting-minutes draft\n• Dedicated capacity and priority",
        "premium_offer": "✨ BeOnMeet Premium\n\nFeatures:\n• Higher recording quality\n• Separate audio file\n• Multilingual transcript with automatic language detection\n• Meeting-minutes draft\n• Dedicated capacity and priority\n\nChoose a plan:",
        "plan_monthly": "1 month · 198,000 toman",
        "plan_quarterly": "3 months · 499,000 toman",
        "plan_halfyear": "6 months · 799,000 toman",
        "calendar_connected": "✅ Calendar connected",
        "calendar_disconnected": "⚠️ Calendar is not connected yet\n{url}",
        "start": "Hi 👋 I’m BeOnMeet.\n\nSend me a Google Meet link. Remember to invite {bot_email} to the same calendar event. I’ll join on time, record the meeting, and send the file here afterward.\n\nThe meeting can be in any language; transcription is multilingual and detects the language automatically.\n\n{auth_status}",
        "now_prompt": "Okay. Send the Google Meet link and I’ll try to join right now.",
        "calendar_error": "⚠️ I saved your request, but I could not read Google Calendar right now. Please send the link again shortly.",
        "event_found": "✅ Got it. I found the calendar event too.\n{meet_url}\n🕒 {when}",
        "event_missing": "⚠️ I saved the link, but I still cannot see this meeting on {bot_email}'s calendar.\n\nInvite {bot_email} to the event. If it is already invited, set “Add invitations to my calendar” to “From everyone” or accept the invitation, then send the link again.\n\nIf the meeting has already started:\n/now {meet_url}",
        "send_link": "Send me a Google Meet link, for example:\nhttps://meet.google.com/abc-defg-hij",
        "queue_premium": "⚡ Premium and overflow capacity are currently full. Your request has Premium priority and is number {position} in the Premium queue. I’ll join as soon as a worker is free.",
        "queue_free": "⏳ Free recorders are currently full. Your request is number {position} in the queue. I’ll join automatically when capacity is available.",
        "launch_premium": "⚡ A dedicated Premium worker is reserved. I’m joining the meeting…\n{meet_url}",
        "launch_priority": "⚡ I’m using available capacity with Premium priority and joining now…\n{meet_url}",
        "launch_free": "⏳ Join request sent. I’m entering the meeting…\n{meet_url}",
        "dispatch_retry": "⚠️ I could not reach a recorder right now. I’ll retry automatically.\n{meet_url}",
        "queue_expired": "⌛ No recorder became available before the meeting ended, so the request was removed from the queue.",
        "premium_ready": "⚡ Premium capacity is free now. I’m joining the meeting…\n{meet_url}",
        "queue_ready": "✅ Your turn is up. I’m joining the meeting now…\n{meet_url}",
        "waiting_admission": "🚪 I’m at the meeting door. Google Meet is waiting for the host to admit me. Recording starts automatically after I enter.",
        "recording_started": "🎥 I joined the meeting and recording has started.",
        "recording_ready_caption": "🎥 Your meeting recording is ready",
        "recording_finished": "✅ The meeting ended. I’m sending your recording now…",
        "audio_ready_caption": "🎧 Your separate meeting audio file is ready",
        "transcribing": "📝 I’m preparing the transcript with automatic language detection. Long meetings can take a little while…",
        "transcript_header": "BeOnMeet automatic meeting transcript",
        "transcript_warning": "Note: this transcript was generated automatically and may contain errors.",
        "transcript_detected": "Detected languages: {languages}",
        "transcript_ready_caption": "📝 Your transcript is ready. The original meeting languages are preserved and not translated.",
        "transcript_empty": "📝 I could not extract a usable transcript. The audio may have been too quiet or unclear.",
        "transcript_error": "⚠️ The audio file is ready, but transcription failed this time. Your video and audio are safe.",
        "delivery_error": "⚠️ Recording finished, but Telegram delivery failed. The file is temporarily retained.",
        "large_video": "The video is large, so I’ll send it in {count} playable parts.",
        "video_part": "Part {index} of {count}",
        "payment_confirmed": "✨ Payment confirmed and Premium activated.\nActive until {until}.",
    },
    "de": {
        "language_choose": "🌐 Wähle die Sprache des Bots. Die Sprache des Meetings ist davon unabhängig und wird automatisch erkannt.",
        "language_changed": "✅ Die Bot Sprache wurde auf Deutsch umgestellt.",
        "new_prompt": "Sende den Google Meet Link hier. Wenn der Termin im Kalender steht, trete ich pünktlich bei. Wenn er schon läuft, nutze „⚡ Sofort beitreten“.",
        "admin_ready": "Der Adminbereich ist bereit 👇\n{url}\n\nDieser Link ist 15 Minuten gültig.",
        "admin_only": "Dieser Bereich ist nur für den Bot Administrator verfügbar 🙂",
        "premium_active": "✨ Dein Premium Plan ist bis {until} aktiv.\n\nPremium Funktionen:\n• Höhere Aufnahmequalität\n• Separate Audiodatei\n• Mehrsprachiges Transkript mit automatischer Spracherkennung\n• Entwurf eines Sitzungsprotokolls\n• Eigene Kapazität und Priorität",
        "premium_offer": "✨ BeOnMeet Premium\n\nFunktionen:\n• Höhere Aufnahmequalität\n• Separate Audiodatei\n• Mehrsprachiges Transkript mit automatischer Spracherkennung\n• Entwurf eines Sitzungsprotokolls\n• Eigene Kapazität und Priorität\n\nWähle einen Plan:",
        "plan_monthly": "1 Monat · 198.000 Toman",
        "plan_quarterly": "3 Monate · 499.000 Toman",
        "plan_halfyear": "6 Monate · 799.000 Toman",
        "calendar_connected": "✅ Kalender verbunden",
        "calendar_disconnected": "⚠️ Kalender ist noch nicht verbunden\n{url}",
        "start": "Hallo 👋 Ich bin BeOnMeet.\n\nSende mir einen Google Meet Link. Lade außerdem {bot_email} zum selben Kalendereintrag ein. Ich trete pünktlich bei, nehme das Meeting auf und sende dir die Datei danach hier.\n\nDas Meeting kann in jeder Sprache stattfinden. Das Transkript ist mehrsprachig und erkennt die Sprache automatisch.\n\n{auth_status}",
        "now_prompt": "Okay. Sende den Google Meet Link und ich versuche sofort beizutreten.",
        "calendar_error": "⚠️ Deine Anfrage wurde gespeichert, aber Google Calendar war gerade nicht erreichbar. Sende den Link bitte gleich noch einmal.",
        "event_found": "✅ Erledigt. Den Kalendereintrag habe ich ebenfalls gefunden.\n{meet_url}\n🕒 {when}",
        "event_missing": "⚠️ Der Link wurde gespeichert, aber ich sehe dieses Meeting noch nicht im Kalender von {bot_email}.\n\nLade {bot_email} zum Termin ein. Falls die Einladung bereits gesendet wurde, stelle „Add invitations to my calendar“ auf „From everyone“ oder akzeptiere die Einladung und sende den Link erneut.\n\nWenn das Meeting bereits läuft:\n/now {meet_url}",
        "send_link": "Sende mir einen Google Meet Link, zum Beispiel:\nhttps://meet.google.com/abc-defg-hij",
        "queue_premium": "⚡ Premium und Zusatzkapazität sind gerade ausgelastet. Deine Anfrage hat Premium Priorität und ist Nummer {position} in der Premium Warteschlange. Sobald ein Worker frei ist, trete ich bei.",
        "queue_free": "⏳ Die kostenlosen Recorder sind gerade ausgelastet. Deine Anfrage ist Nummer {position} in der Warteschlange. Sobald Kapazität frei ist, trete ich automatisch bei.",
        "launch_premium": "⚡ Ein eigener Premium Worker ist reserviert. Ich trete dem Meeting bei…\n{meet_url}",
        "launch_priority": "⚡ Ich nutze freie Kapazität mit Premium Priorität und trete jetzt bei…\n{meet_url}",
        "launch_free": "⏳ Beitrittsanfrage gesendet. Ich trete dem Meeting bei…\n{meet_url}",
        "dispatch_retry": "⚠️ Der Recorder ist gerade nicht erreichbar. Ich versuche es automatisch erneut.\n{meet_url}",
        "queue_expired": "⌛ Vor Ende des Meetings wurde kein Recorder frei. Die Anfrage wurde aus der Warteschlange entfernt.",
        "premium_ready": "⚡ Premium Kapazität ist jetzt frei. Ich trete dem Meeting bei…\n{meet_url}",
        "queue_ready": "✅ Du bist jetzt dran. Ich trete dem Meeting bei…\n{meet_url}",
        "waiting_admission": "🚪 Ich bin vor dem Meeting. Google Meet wartet darauf, dass der Host mich zulässt. Nach dem Beitritt startet die Aufnahme automatisch.",
        "recording_started": "🎥 Ich bin im Meeting und die Aufnahme läuft.",
        "recording_ready_caption": "🎥 Deine Meeting Aufnahme ist bereit",
        "recording_finished": "✅ Das Meeting ist beendet. Ich sende dir jetzt die Aufnahme…",
        "audio_ready_caption": "🎧 Deine separate Audiodatei des Meetings ist bereit",
        "transcribing": "📝 Ich erstelle das Transkript mit automatischer Spracherkennung. Bei langen Meetings kann das etwas dauern…",
        "transcript_header": "Automatisches BeOnMeet Meeting Transkript",
        "transcript_warning": "Hinweis: Dieses Transkript wurde automatisch erstellt und kann Fehler enthalten.",
        "transcript_detected": "Erkannte Sprachen: {languages}",
        "transcript_ready_caption": "📝 Dein Transkript ist bereit. Die Originalsprachen des Meetings bleiben erhalten und werden nicht übersetzt.",
        "transcript_empty": "📝 Es konnte kein brauchbares Transkript erstellt werden. Der Ton war möglicherweise zu leise oder unklar.",
        "transcript_error": "⚠️ Die Audiodatei ist bereit, aber die Transkription ist diesmal fehlgeschlagen. Video und Audio sind weiterhin vorhanden.",
        "delivery_error": "⚠️ Die Aufnahme ist beendet, aber der Versand über Telegram ist fehlgeschlagen. Die Datei wird vorübergehend gespeichert.",
        "large_video": "Das Video ist groß, daher sende ich es in {count} abspielbaren Teilen.",
        "video_part": "Teil {index} von {count}",
        "payment_confirmed": "✨ Zahlung bestätigt und Premium aktiviert.\nAktiv bis {until}.",
    },
}

PROFILE_TEXT = {
    "fa": {
        "description": "لینک Google Meet رو بفرست. سر وقت وارد جلسه می‌شم، ضبط می‌کنم و فایل رو همینجا می‌فرستم. متن جلسه چندزبانه است.",
        "short": "ضبط خودکار Google Meet و متن چندزبانه",
        "commands": {
            "start": "راهنمای استفاده",
            "plans": "پلن ویژه و خرید اشتراک",
            "now": "ورود فوری به جلسه",
            "language": "تغییر زبان",
            "admin": "پنل مدیریت",
        },
    },
    "en": {
        "description": "Send a Google Meet link. I join on time, record it and send the file here. Multilingual transcription is supported.",
        "short": "Automatic Google Meet recording and multilingual transcripts",
        "commands": {
            "start": "How to use BeOnMeet",
            "plans": "Premium plans and subscription",
            "now": "Join a meeting now",
            "language": "Change language",
            "admin": "Admin panel",
        },
    },
    "de": {
        "description": "Sende einen Google Meet Link. Ich trete pünktlich bei, nehme auf und sende die Datei hier. Mehrsprachige Transkription ist verfügbar.",
        "short": "Automatische Google Meet Aufnahme und mehrsprachige Transkripte",
        "commands": {
            "start": "BeOnMeet verwenden",
            "plans": "Premium Pläne und Abo",
            "now": "Sofort einem Meeting beitreten",
            "language": "Sprache ändern",
            "admin": "Adminbereich",
        },
    },
}


def normalize_language(value: str | None, default: str = "en") -> str:
    value = (value or "").strip().lower().replace("_", "-")
    if value.startswith("fa") or value.startswith("per"):
        return "fa"
    if value.startswith("de"):
        return "de"
    if value.startswith("en"):
        return "en"
    return default if default in SUPPORTED_LANGUAGES else "en"


def tr(language: str, key: str, **kwargs: Any) -> str:
    lang = normalize_language(language)
    template = MESSAGES.get(lang, MESSAGES["en"]).get(key)
    if template is None:
        template = MESSAGES["en"].get(key, key)
    return template.format(**kwargs)


def menu(language: str) -> dict[str, str]:
    return MENU_LABELS[normalize_language(language)]


def profile(language: str) -> dict[str, Any]:
    return PROFILE_TEXT[normalize_language(language)]


BUTTON_ACTIONS: dict[str, str] = {}
for _lang, _labels in MENU_LABELS.items():
    BUTTON_ACTIONS[_labels["new"]] = "/new"
    BUTTON_ACTIONS[_labels["premium"]] = "/plans"
    BUTTON_ACTIONS[_labels["now"]] = "/now"
    BUTTON_ACTIONS[_labels["help"]] = "/start"
    BUTTON_ACTIONS[_labels["language"]] = "/language"
    BUTTON_ACTIONS[_labels["admin"]] = "/admin"

for _lang, _button in LANGUAGE_BUTTONS.items():
    BUTTON_ACTIONS[_button] = f"/setlanguage {_lang}"
