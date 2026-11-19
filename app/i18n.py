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
        "auto": "✨📅 همه جلسات",
        "help": "❓ راهنما",
        "language": "🌐 زبان",
        "admin": "⚙️ پنل مدیریت",
        "placeholder": "لینک Google Meet رو بفرست…",
    },
    "en": {
        "new": "🎬 New recording",
        "premium": "✨ Premium",
        "now": "⚡ Join now",
        "auto": "✨📅 All meetings",
        "help": "❓ Help",
        "language": "🌐 Language",
        "admin": "⚙️ Admin panel",
        "placeholder": "Send a Google Meet link…",
    },
    "de": {
        "new": "🎬 Neue Aufnahme",
        "premium": "✨ Premium",
        "now": "⚡ Sofort beitreten",
        "auto": "✨📅 Alle Meetings",
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
        "premium_active": "✨ اشتراک فعلی‌ات تا {until} فعال است.\n\nقوانین: سهمیه بین تمام ضبط‌های همین دوره مشترک است؛ ساعت مانده به ماه بعد منتقل نمی‌شود؛ تمدید خودکار نداریم. اگر سهمیه زودتر تمام شود، خرید مجدد به دوره بعد می‌رود و ساعت همین دوره را اضافه نمی‌کند. برای افزایش فوری با پشتیبانی تماس بگیر.",
        "premium_offer": "✨ پلن‌های BeOnMeet\n\nرایگان: فقط ۱ ضبط آزمایشی.\n\nهر پلن پولی، مجموعِ ساعت ضبط در ۳۰ روز از زمان شروع دوره است؛ می‌توانی این مدت را بین چند جلسه تقسیم کنی. مثلاً Basic مجموعاً ۱۲۰ دقیقه ضبط دارد، نه ۲ ساعت برای هر جلسه.\n\nقوانین مهم:\n• تنها مدت ضبط‌های انجام‌شده از سهمیه کم می‌شود. جلسه‌ای که شروع شده ممکن است از باقی‌مانده بیشتر طول بکشد.\n• ساعت استفاده‌نشده پس از پایان ۳۰ روز از بین می‌رود و به دوره بعد منتقل نمی‌شود.\n• تمدید خودکار و برداشت خودکار بابت ساعت اضافه نداریم.\n• اگر پیش از تمام‌شدن ۳۰ روز سهمیه‌ات تمام شود، ضبط جدید متوقف می‌شود. خرید مجدد پلن، سهمیه همین دوره را شارژ نمی‌کند و دوره ۳۰روزه بعدی را رزرو می‌کند؛ برای افزایش فوری سهمیه با پشتیبانی تماس بگیر.\n\nپلن‌های زیر را انتخاب کن:",
        "free_limit_reached": "🔒 سقف پلن رایگان پر شده\n\nپلن رایگان یک جلسه آزمایشی ضبط می‌کند. ضبط‌های انجام شده و جلسه‌های رایگان در حال اجرا یا صف، جزو این سهمیه حساب می‌شوند. برای ضبط جلسه بعدی یکی از اشتراک‌های ویژه را فعال کن:",
        "plan_monthly": "۱ ماهه · ۱۹۸ هزار تومان",
        "plan_quarterly": "۳ ماهه · ۴۹۹ هزار تومان",
        "plan_halfyear": "۶ ماهه · ۷۹۹ هزار تومان",
        "plan_basic": "Basic · ۲ ساعت در ۳۰ روز · ۲۹۸٬۰۰۰ تومان",
        "plan_pro": "Pro · ۶ ساعت در ۳۰ روز · ۴۹۸٬۰۰۰ تومان",
        "plan_business": "Business · ۱۵ ساعت در ۳۰ روز · ۹۹۸٬۰۰۰ تومان",
        "paid_quota_reached": "⏱ سهمیه این دوره تمام شده یا برای جلسه در صف رزرو شده است: {used} از {limit} دقیقه مصرف ثبت‌شده. تا شروع دوره بعد ضبط جدید پذیرفته نمی‌شود. خرید دوباره همین پلن ساعت این دوره را اضافه نمی‌کند؛ برای افزایش فوری با پشتیبانی تماس بگیر.",
        "quota_remaining": "⏱ باقیمانده این دوره: {minutes} دقیقه (مصرف شده: {used} دقیقه). سهمیه مجموع همه جلسه‌هاست، نه سهمیه هر جلسه.",
        "quota_legacy": "اشتراک قدیمی: محدودیت ساعتی جدید شامل این دوره نمی‌شود.",
        "sales_paused": "⏳ ظرفیت فعلی ضبط BeOnMeet تکمیل شده و خرید اشتراک جدید موقتاً بسته است. هیچ پرداختی انجام نده. پس از آزادشدن ظرفیت دوباره /plans را بررسی کن.",
        "calendar_connected": "✅ کلندر وصله",
        "calendar_disconnected": "⚠️ کلندر هنوز وصل نیست\n{url}",
        "auto_premium_only": "✨📅 همه جلسات فقط در پلن ویژه فعال است. با Premium یک بار Google Calendar خودت رو وصل می‌کنی و BeOnMeet تمام Google Meetهای Calendarهای قابل دسترسی رو خودکار پیدا می‌کنه و سر وقت وارد می‌شه.\n\nبرای فعال‌سازی یکی از پلن‌ها رو انتخاب کن:",
        "auto_premium_status": "✨ قابلیت همه جلسات مخصوص Premium است. از بخش پلن ویژه فعالش کن.",
        "auto_connect": "📅 برای حالت همه جلسات، فقط یک بار Google Calendar خودت رو وصل کن:\n{url}\n\nبعد از اتصال، حالت خودکار روشن می‌شه و همه کلندرهای قابل دسترسی این اکانت بررسی می‌شن. دیگه لازم نیست لینک جلسه‌ها رو یکی یکی بفرستی.",
        "auto_enabled": "✅ حالت همه جلسات روشن شد. از این به بعد هر Google Meet داخل همه کلندرهای قابل دسترسی اکانت متصل رو خودکار تشخیص می‌دم و سر وقت واردش می‌شم. جلسه‌ای که Decline کرده باشی نادیده گرفته می‌شه. ممکنه میزبان لازم باشه Recorder رو Admit کنه.",
        "auto_disabled": "⏸ حالت همه جلسات خاموش شد. اتصال کلندر حفظ می‌شه و هر وقت بخوای می‌تونی دوباره روشنش کنی.",
        "auto_status_on": "📅 حالت همه جلسات روشن است",
        "auto_status_off": "📅 حالت همه جلسات خاموش است. از دکمه «همه جلسات» روشنش کن.",
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
        "transcript_error": "⚠️ فایل صوتی آماده است ولی ساخت متن این بار خطا خورد. ویدیو و صوتت امن هستند و خودکار دوباره امتحان می‌کنم.",
        "delivery_error": "⚠️ ضبط تموم شده ولی ارسالش به تلگرام خطا خورد. فایل فعلاً در حافظه موقت نگه داشته شده.",
        "large_video": "حجم ویدیو زیاده، برای همین توی {count} قسمت قابل پخش می‌فرستم.",
        "large_video_download": "🎥 فایل کامل جلسه آماده است.\n\n⬇️ دانلود یک‌تکه:\n{url}\n\nاین لینک تا {hours} ساعت معتبر است.",
        "large_audio_download": "🎧 فایل صوتی کامل جلسه آماده است.\n\n⬇️ دانلود فایل صوتی:\n{url}\n\nاین لینک تا {hours} ساعت معتبر است.",
        "video_part": "قسمت {index} از {count}",
        "payment_confirmed": "✅ پرداخت پلن {plan} تأیید شد.\nدوره ۳۰روزه جدید تا {until} فعال است و مجموعاً {hours} ساعت ضبط دارد. تمدید خودکار ندارد؛ ساعت استفاده‌نشده به دوره بعد منتقل نمی‌شود.",
    },
        "manual_mode_notice": "📩 فعلاً فقط ضبط با ارسال لینک جلسه فعال است. برای جلسه آینده، ایمیل رکوردر را به دعوت تقویم اضافه کن؛ برای جلسه در حال اجرا از «ورود فوری» استفاده کن.",
        "auto_unavailable": "⏸ قابلیت ضبط خودکار «همه جلسات» فعلاً فعال نیست و در پلن‌های فروشی ارائه نمی‌شود. برای ضبط، لینک هر جلسه را مستقیم در ربات بفرست.",
        "payment_scheduled": "✅ پرداخت پلن {plan} تأیید شد، اما چون هنوز اشتراک فعالی داری، این خرید شارژ فوری ساعت‌ها نیست.\nدوره جدید از {starts} شروع می‌شود و تا {until} ادامه دارد؛ مجموعاً {hours} ساعت ضبط در آن دوره خواهی داشت. سهمیه دوره فعلی تغییر نمی‌کند.",
        "renewal_scheduled": "📅 دوره بعدی که قبلاً خریداری کرده‌ای: {plan}\nشروع: {starts} | پایان: {until}\nاین خرید ساعت ضبط دوره فعلی را افزایش نمی‌دهد.",
        "plan_rules_short": "ℹ️ هر پلن مجموعِ ۲/۶/۱۵ ساعت ضبط در ۳۰ روز است؛ ساعت‌های مانده منتقل نمی‌شود. خرید دوباره در دوره فعال، شارژ فوری نیست و برای دوره بعد رزرو می‌شود. برای ساعت اضافه فوری با پشتیبانی تماس بگیر.",
        "payment_confirmed_legacy": "✅ پرداخت پلن قبلی {plan} تأیید شد. اعتبار تا {until} است؛ شرایط همان اشتراک قدیمی اعمال می‌شود.",
    "en": {
        "language_choose": "🌐 Choose the bot language. Meeting language is independent and detected automatically.",
        "language_changed": "✅ Bot language changed to English.",
        "new_prompt": "Send the Google Meet link here. If it is on the calendar, I’ll join on time. If it has already started, use “⚡ Join now”.",
        "admin_ready": "The admin panel is ready 👇\n{url}\n\nThis link is valid for 15 minutes.",
        "admin_only": "This section is only available to the bot administrator 🙂",
        "premium_active": "✨ Your current subscription is active until {until}.\n\nThe allowance is shared across meetings; unused minutes do not roll over; there is no automatic renewal. Another purchase schedules a later period, not more hours now. Contact support if you need extra hours immediately.",
        "premium_offer": "✨ BeOnMeet plans\n\nFree: one trial recording only.\n\nEach paid plan grants a TOTAL recording allowance for a 30-day period, shared across all your meetings. Basic is 120 recorded minutes total, not 2 hours per meeting.\n\nImportant rules:\n• Completed recording durations count toward the allowance. A meeting already recording may run beyond the remaining time.\n• Unused minutes expire after 30 days; they do not roll over.\n• No automatic renewals and no automatic overage charges.\n• If you use your allowance early, you cannot start more recordings until a new period. Buying another plan schedules the NEXT 30-day period—it does NOT top up your current allowance. Contact support for immediate additional hours.\n\nChoose a plan:",
        "free_limit_reached": "🔒 Free plan limit reached\n\nThe free plan allows one trial recording. Completed recordings and free meetings already running or queued count toward that allowance. Activate a Premium plan to record another meeting:",
        "plan_monthly": "1 month · 198,000 toman",
        "plan_quarterly": "3 months · 499,000 toman",
        "plan_halfyear": "6 months · 799,000 toman",
        "plan_basic": "Basic · 2 hours / 30 days · 298,000 toman",
        "plan_pro": "Pro · 6 hours / 30 days · 498,000 toman",
        "plan_business": "Business · 15 hours / 30 days · 998,000 toman",
        "paid_quota_reached": "⏱ This period's allowance is exhausted or reserved: {used} of {limit} minutes recorded. No new recording until the next period. Buying the plan again does not top up this period; contact support for immediate extra hours.",
        "quota_remaining": "⏱ Remaining THIS period: {minutes} minutes ({used} minutes used). This is a total across meetings, not an allowance per meeting.",
        "quota_legacy": "Your existing legacy subscription keeps its original unlimited-hours terms for this period.",
        "sales_paused": "⏳ BeOnMeet's current recording capacity is full, so new paid checkout is temporarily paused. Please do not send payment. Check /plans again later.",
        "calendar_connected": "✅ Calendar connected",
        "calendar_disconnected": "⚠️ Calendar is not connected yet\n{url}",
        "auto_premium_only": "✨📅 All meetings is a Premium feature. With Premium, connect Google Calendar once and BeOnMeet automatically detects Google Meet events across your accessible calendars and joins on time.\n\nChoose a plan to activate it:",
        "auto_premium_status": "✨ All meetings is a Premium feature. Activate Premium to use it.",
        "auto_connect": "📅 To use All meetings, connect your Google Calendar once:\n{url}\n\nAfter connecting, automatic mode turns on and all accessible calendars in this Google account are checked. You no longer need to send meeting links one by one.",
        "auto_enabled": "✅ All meetings is on. From now on I will automatically detect every Google Meet across all accessible calendars in the connected Google account and join on time. Declined events are ignored. The host may still need to admit the recorder.",
        "auto_disabled": "⏸ All meetings is off. Your calendar stays connected, so you can turn it back on anytime.",
        "auto_status_on": "📅 All meetings is on",
        "auto_status_off": "📅 All meetings is off. Use the All meetings button to enable it.",
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
        "transcript_error": "⚠️ The audio file is ready, but transcription failed this time. Your video and audio are safe, and I’ll retry automatically.",
        "delivery_error": "⚠️ Recording finished, but Telegram delivery failed. The file is temporarily retained.",
        "large_video": "The video is large, so I’ll send it in {count} playable parts.",
        "large_video_download": "🎥 The full meeting recording is ready.\n\n⬇️ Download the complete file:\n{url}\n\nThis link is valid for {hours} hours.",
        "large_audio_download": "🎧 The full meeting audio is ready.\n\n⬇️ Download the audio file:\n{url}\n\nThis link is valid for {hours} hours.",
        "video_part": "Part {index} of {count}",
        "payment_confirmed": "✅ {plan} payment confirmed. Your 30-day period is active until {until} and includes {hours} total recorded hours. No auto-renewal or rollover.",
    },
        "manual_mode_notice": "📩 Recording works by sending each meeting link. For scheduled meetings invite the recorder email to the event; for live meetings use Join now.",
        "auto_unavailable": "⏸ The All Meetings automatic-calendar feature is temporarily unavailable and is not part of current paid plans. Send each meeting link directly to this bot.",
        "payment_scheduled": "✅ {plan} payment confirmed, but you already have an active subscription. This is NOT an immediate hours top-up.\nThe new period begins {starts} and ends {until}; it will provide {hours} total recorded hours. Your current period balance is unchanged.",
        "renewal_scheduled": "📅 Already purchased next period: {plan}\nStarts {starts} | Ends {until}\nThis does not increase your current period's minutes.",
        "plan_rules_short": "ℹ️ Each plan has a total of 2/6/15 recorded hours over 30 days. Unused hours expire. A second purchase during an active term queues the next period; it is NOT an immediate top-up. Contact support for immediate additional hours.",
        "payment_confirmed_legacy": "✅ Your legacy plan {plan} payment was confirmed. Active until {until}; its original plan terms apply.",
    "de": {
        "language_choose": "🌐 Wähle die Sprache des Bots. Die Sprache des Meetings ist davon unabhängig und wird automatisch erkannt.",
        "language_changed": "✅ Die Bot Sprache wurde auf Deutsch umgestellt.",
        "new_prompt": "Sende den Google Meet Link hier. Wenn der Termin im Kalender steht, trete ich pünktlich bei. Wenn er schon läuft, nutze „⚡ Sofort beitreten“.",
        "admin_ready": "Der Adminbereich ist bereit 👇\n{url}\n\nDieser Link ist 15 Minuten gültig.",
        "admin_only": "Dieser Bereich ist nur für den Bot Administrator verfügbar 🙂",
        "premium_active": "✨ Dein aktuelles Abo läuft bis {until}.\n\nDie Stunden gelten insgesamt für alle Meetings; Restminuten verfallen, keine automatische Verlängerung. Ein weiterer Kauf gilt für den nächsten Zeitraum, nicht als sofortige Aufladung. Für sofort mehr Stunden Support kontaktieren.",
        "premium_offer": "✨ BeOnMeet Tarife\n\nKostenlos: nur eine Probeaufnahme.\n\nJeder Tarif umfasst eine GESAMTE Aufnahmezeit für 30 Tage, verteilt auf alle Meetings. Basic bedeutet 120 Minuten insgesamt, nicht 2 Stunden pro Meeting.\n\nWichtige Regeln:\n• Die Dauer abgeschlossener Aufnahmen wird angerechnet. Eine laufende Aufnahme kann die Restzeit überschreiten.\n• Nicht genutzte Minuten verfallen nach 30 Tagen; keine Übertragung.\n• Keine automatische Verlängerung und keine automatische Mehrberechnung.\n• Ist das Kontingent vorzeitig verbraucht, sind neue Aufnahmen bis zum nächsten Zeitraum gesperrt. Ein weiterer Kauf beginnt erst im NÄCHSTEN 30-Tage-Zeitraum und lädt die aktuelle Zeit NICHT auf. Für sofort zusätzliche Stunden den Support kontaktieren.\n\nTarif wählen:",
        "free_limit_reached": "🔒 Limit des kostenlosen Plans erreicht\n\nDer kostenlose Plan erlaubt eine Probeaufnahme. Abgeschlossene Aufnahmen sowie kostenlose Meetings, die bereits laufen oder in der Warteschlange stehen, zählen zu diesem Kontingent. Aktiviere Premium, um ein weiteres Meeting aufzunehmen:",
        "plan_monthly": "1 Monat · 198.000 Toman",
        "plan_quarterly": "3 Monate · 499.000 Toman",
        "plan_halfyear": "6 Monate · 799.000 Toman",
        "plan_basic": "Basic · 2 Stunden / 30 Tage · 298.000 Toman",
        "plan_pro": "Pro · 6 Stunden / 30 Tage · 498.000 Toman",
        "plan_business": "Business · 15 Stunden / 30 Tage · 998.000 Toman",
        "paid_quota_reached": "⏱ Das Kontingent ist verbraucht oder reserviert: {used} von {limit} Minuten. Bis zum nächsten Zeitraum sind keine neuen Aufnahmen möglich. Ein erneuter Kauf lädt den aktuellen Zeitraum NICHT auf; bitte Support kontaktieren.",
        "quota_remaining": "⏱ Verbleibend in DIESEM Zeitraum: {minutes} Minuten ({used} Minuten verbraucht). Das Kontingent gilt insgesamt für alle Meetings.",
        "quota_legacy": "Dein bestehender Altvertrag behält die bisherigen unbegrenzten Aufnahmestunden in diesem Zeitraum.",
        "sales_paused": "⏳ Die aktuelle Aufnahmekapazität von BeOnMeet ist ausgebucht. Neue Abos können momentan nicht gekauft werden. Bitte zahle nicht und prüfe /plans später erneut.",
        "calendar_connected": "✅ Kalender verbunden",
        "calendar_disconnected": "⚠️ Kalender ist noch nicht verbunden\n{url}",
        "auto_premium_only": "✨📅 Alle Meetings ist eine Premium Funktion. Mit Premium verbindest du deinen Google Kalender einmal. Danach erkennt BeOnMeet Google Meet Termine in allen verfügbaren Kalendern automatisch und tritt pünktlich bei.\n\nWähle einen Plan, um die Funktion zu aktivieren:",
        "auto_premium_status": "✨ Alle Meetings ist eine Premium Funktion. Aktiviere Premium, um sie zu nutzen.",
        "auto_connect": "📅 Für Alle Meetings verbinde deinen Google Kalender einmal:\n{url}\n\nNach der Verbindung wird der automatische Modus aktiviert und alle verfügbaren Kalender dieses Google Kontos werden geprüft. Du musst Meeting Links nicht mehr einzeln senden.",
        "auto_enabled": "✅ Alle Meetings ist aktiviert. Ab jetzt erkenne ich jedes Google Meet in allen verfügbaren Kalendern des verbundenen Google Kontos automatisch und trete pünktlich bei. Abgelehnte Termine werden ignoriert. Der Host muss den Recorder möglicherweise noch zulassen.",
        "auto_disabled": "⏸ Alle Meetings ist deaktiviert. Die Kalenderverbindung bleibt bestehen und du kannst den Modus jederzeit wieder aktivieren.",
        "auto_status_on": "📅 Alle Meetings ist aktiviert",
        "auto_status_off": "📅 Alle Meetings ist deaktiviert. Aktiviere den Modus über die Schaltfläche Alle Meetings.",
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
        "transcript_error": "⚠️ Die Audiodatei ist bereit, aber die Transkription ist diesmal fehlgeschlagen. Video und Audio sind sicher und ich versuche es automatisch erneut.",
        "delivery_error": "⚠️ Die Aufnahme ist beendet, aber der Versand über Telegram ist fehlgeschlagen. Die Datei wird vorübergehend gespeichert.",
        "large_video": "Das Video ist groß, daher sende ich es in {count} abspielbaren Teilen.",
        "large_video_download": "🎥 Die vollständige Meeting Aufnahme ist bereit.\n\n⬇️ Vollständige Datei herunterladen:\n{url}\n\nDieser Link ist {hours} Stunden gültig.",
        "large_audio_download": "🎧 Die vollständige Audiodatei des Meetings ist bereit.\n\n⬇️ Audiodatei herunterladen:\n{url}\n\nDieser Link ist {hours} Stunden gültig.",
        "video_part": "Teil {index} von {count}",
        "payment_confirmed": "✅ Zahlung für {plan} bestätigt. Dein 30-Tage-Zeitraum ist bis {until} aktiv und enthält {hours} Stunden Aufnahme insgesamt. Keine automatische Verlängerung, keine Übertragung.",
    },
        "plan_rules_short": "ℹ️ Jeder Tarif enthält insgesamt 2/6/15 Aufnahmestunden in 30 Tagen. Reststunden verfallen. Ein zweiter Kauf während des laufenden Abos gilt für den nächsten Zeitraum, NICHT als sofortige Aufladung. Für zusätzliche Stunden Support kontaktieren.",
        "payment_confirmed_legacy": "✅ Zahlung des bisherigen Tarifs {plan} bestätigt. Gültig bis {until}; die ursprünglichen Tarifbedingungen gelten.",
}

PROFILE_TEXT = {
        "manual_mode_notice": "📩 Zur Aufnahme jeden Meeting-Link einzeln senden. Bei geplanten Meetings die Recorder-E-Mail zum Termin einladen; für laufende Meetings Sofort beitreten verwenden.",
        "auto_unavailable": "⏸ Die automatische Funktion Alle Meetings ist derzeit nicht verfügbar und nicht in den kostenpflichtigen Tarifen enthalten. Bitte Meeting-Links einzeln senden.",
        "payment_scheduled": "✅ Zahlung für {plan} bestätigt. Du hast noch ein aktives Abo: Das ist KEINE sofortige Stundenaufladung.\nDer neue Zeitraum läuft von {starts} bis {until}, dann stehen {hours} Stunden insgesamt zur Verfügung. Dein aktuelles Kontingent bleibt unverändert.",
        "renewal_scheduled": "📅 Bereits gekaufter Folgezeitraum: {plan}\nBeginn {starts} | Ende {until}\nKeine zusätzlichen Minuten für den aktuellen Zeitraum.",
    "fa": {
        "description": "لینک Google Meet رو بفرست. سر وقت وارد جلسه می‌شم، ضبط می‌کنم و فایل رو همینجا می‌فرستم. متن جلسه چندزبانه است.",
        "short": "ضبط Google Meet با ارسال لینک و متن چندزبانه",
        "commands": {
            "start": "راهنمای استفاده",
            "plans": "پلن ویژه و خرید اشتراک",
            "now": "ورود فوری به جلسه",
            "auto": "همه جلسات خودکار ویژه",
            "language": "تغییر زبان",
            "admin": "پنل مدیریت",
        },
    },
    "en": {
        "description": "Send a Google Meet link. I join on time, record it and send the file here. Multilingual transcription is supported.",
        "short": "Google Meet link recording and multilingual transcripts",
        "commands": {
            "start": "How to use BeOnMeet",
            "plans": "Premium plans and subscription",
            "now": "Join a meeting now",
            "auto": "Premium automatic all meetings",
            "language": "Change language",
            "admin": "Admin panel",
        },
    },
    "de": {
        "description": "Sende einen Google Meet Link. Ich trete pünktlich bei, nehme auf und sende die Datei hier. Mehrsprachige Transkription ist verfügbar.",
        "short": "Google Meet Links aufnehmen und mehrsprachige Transkripte",
        "commands": {
            "start": "BeOnMeet verwenden",
            "plans": "Premium Pläne und Abo",
            "now": "Sofort einem Meeting beitreten",
            "auto": "Premium Funktion Alle Meetings",
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
    BUTTON_ACTIONS[_labels["auto"]] = "/auto"
    BUTTON_ACTIONS[_labels["help"]] = "/start"
    BUTTON_ACTIONS[_labels["language"]] = "/language"
    BUTTON_ACTIONS[_labels["admin"]] = "/admin"

for _lang, _button in LANGUAGE_BUTTONS.items():
    BUTTON_ACTIONS[_button] = f"/setlanguage {_lang}"
