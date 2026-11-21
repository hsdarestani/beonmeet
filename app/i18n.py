from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("fa", "en", "de")
DEFAULT_LANGUAGE = "fa"

LANGUAGE_BUTTONS = {
    "fa": "🇮🇷 فارسی",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
}

MENU_LABELS = {
    "fa": {
        "new": "🎬 ضبط جلسه جدید",
        "premium": "⏱ شارژ ساعت ضبط",
        "now": "⚡ ورود فوری",
        "auto": "✨📅 همه جلسات",
        "help": "❓ راهنما",
        "language": "🌐 زبان",
        "admin": "⚙️ پنل مدیریت",
        "placeholder": "لینک Google Meet رو بفرست…",
    },
    "en": {
        "new": "🎬 New recording",
        "premium": "⏱ Buy recording hours",
        "now": "⚡ Join now",
        "auto": "✨📅 All meetings",
        "help": "❓ Help",
        "language": "🌐 Language",
        "admin": "⚙️ Admin panel",
        "placeholder": "Send a Google Meet link…",
    },
    "de": {
        "new": "🎬 Neue Aufnahme",
        "premium": "⏱ Aufnahmestunden kaufen",
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
        "premium_active": "⏱ موجودی ساعت ضبط BeOnMeet\n\nساعت‌های خریداری‌شده تاریخ انقضا ندارند و خرید بعدی به موجودی اضافه می‌شود.",
        "premium_offer": "⏱ شارژ ساعت ضبط BeOnMeet\n\nاینجا اشتراک ماهانه یا پلن نداریم: فقط ساعت ضبط می‌خری.\n\n• هر خرید فوراً به موجودی قبلی اضافه می‌شود.\n• اعتبار ساعت‌ها تاریخ انقضا ندارد؛ هر وقت خواستی مصرفش کن.\n• زمان ضبط موفق هر جلسه از موجودی کم می‌شود؛ اگر یک ضبط در حال اجرا بیشتر از باقی‌مانده طول بکشد، مازاد از شارژ بعدی کسر می‌شود.\n• تمدید خودکار و هزینه اضافه خودکار نداریم.\n• خرید دوباره همان گزینه، ساعت‌های بیشتری به کیف پول اضافه می‌کند.\n\nمبلغ‌های فعلی خرید ساعت:",
        "free_limit_reached": "⌛ اعتبار رایگان ضبطت تموم شده. برای ضبط بعدی ساعت ضبط شارژ کن؛ اعتبار خریداری‌شده تاریخ انقضا نداره.",
        "plan_monthly": "۱ ماهه · ۱۹۸ هزار تومان",
        "plan_quarterly": "۳ ماهه · ۴۹۹ هزار تومان",
        "plan_halfyear": "۶ ماهه · ۷۹۹ هزار تومان",
        "plan_basic": "➕ خرید ۲ ساعت ضبط · ۲۹۸٬۰۰۰ تومان",
        "plan_pro": "➕ خرید ۶ ساعت ضبط · ۴۹۸٬۰۰۰ تومان",
        "plan_business": "➕ خرید ۱۵ ساعت ضبط · ۹۹۸٬۰۰۰ تومان",
        "paid_quota_reached": "⏱ موجودی ساعت ضبط کافی نیست؛ می‌توانی هر زمان دوباره ساعت بخری و به اعتبار قبلی اضافه کنی.",
        "quota_remaining": "⏱ موجودی اعتبار ضبط: {minutes} دقیقه",
        "quota_legacy": "شرایط ویژه اشتراک قدیمی تا تاریخ پایان آن حفظ شده است.",
        "sales_paused": "⏳ به‌دلیل محدودیت ظرفیت سرور، فروش ساعت بیشتر موقتاً متوقف شده است. پرداخت نکن و بعداً /credits را دوباره بررسی کن.",
        "calendar_connected": "✅ کلندر وصله",
        "calendar_disconnected": "⚠️ کلندر هنوز وصل نیست\n{url}",
        "auto_premium_only": "قابلیت «همه جلسات» فعلاً غیرفعال است. لینک هر جلسه را جداگانه بفرست.",
        "auto_premium_status": "✨ قابلیت همه جلسات مخصوص Premium است. از بخش پلن ویژه فعالش کن.",
        "auto_connect": "📅 برای حالت همه جلسات، فقط یک بار Google Calendar خودت رو وصل کن:\n{url}\n\nبعد از اتصال، حالت خودکار روشن می‌شه و همه کلندرهای قابل دسترسی این اکانت بررسی می‌شن. دیگه لازم نیست لینک جلسه‌ها رو یکی یکی بفرستی.",
        "auto_enabled": "✅ حالت همه جلسات روشن شد. از این به بعد هر Google Meet داخل همه کلندرهای قابل دسترسی اکانت متصل رو خودکار تشخیص می‌دم و سر وقت واردش می‌شم. جلسه‌ای که Decline کرده باشی نادیده گرفته می‌شه. ممکنه میزبان لازم باشه Recorder رو Admit کنه.",
        "auto_disabled": "⏸ حالت همه جلسات خاموش شد. اتصال کلندر حفظ می‌شه و هر وقت بخوای می‌تونی دوباره روشنش کنی.",
        "auto_status_on": "📅 حالت همه جلسات روشن است",
        "auto_status_off": "📅 حالت همه جلسات خاموش است. از دکمه «همه جلسات» روشنش کن.",
        "start": "سلام 👋 من BeOnMeet هستم.\n\nلینک Google Meet رو برام بفرست. برای دیدن اعتبار رایگان شروع و ساعت‌های ضبط، /credits رو بزن. فقط یادت باشه {bot_email} رو هم به همون ایونت کلندر دعوت کنی. سر وقت وارد جلسه می‌شم، ضبطش می‌کنم و آخرش فایل رو همینجا برات می‌فرستم.\n\nزبان جلسه مهم نیست؛ متن جلسه چندزبانه است و زبان رو خودکار تشخیص می‌دم.\n\n{auth_status}",
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
        "join_connecting": "🔄 در حال اتصال به مرورگر و بازکردن Google Meet هستم. هنوز وارد جلسه نشده‌ام و از اعتبار ضبطت چیزی کم نشده.",
        "join_still_unconfirmed": "⚠️ ورود به جلسه هنوز تأیید نشده؛ در حال تلاش مجدد هستم. تا زمانی که ضبط واقعاً انجام و فایل تحویل داده نشود، اعتباری کم نمی‌شود.",
        "join_guest_access_possible": "🚫 هنوز نتوانستم وارد جلسه شوم. Google Meet ممکن است ورود مهمان ناشناس یا ربات را بدون نمایش درخواست به میزبان رد کرده باشد. برای *تست همین جلسه*، میزبان می‌تواند در Host controls → Meeting access حالت Open را انتخاب کند؛ توجه کن در این حالت هر دارنده لینک بدون تأیید وارد می‌شود. راه امن‌تر برای جلسات مشتری، اتصال ربات با حساب Google معتبر و دعوت آن به جلسه است. هنوز ضبط شروع نشده و اعتباری کم نشده.",
        "join_expired_without_recording": "⌛ این درخواست ورود در مهلت تعیین‌شده به ضبط نرسید و از وضعیت فعال ربات خارج شد. اگر جلسه هنوز برقرار است می‌توانی دوباره لینک را ارسال کنی. برای این درخواست ضبط موفقی ثبت نشده و اعتباری از آن کم نشده است.",
        "join_already_processing": "⏳ برای همین لینک یک درخواست ورود در جریان است. لطفاً درخواست تازه نفرست؛ وقتی وارد شوم یا ضبط شروع شود خبر می‌دهم.",
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
        "delivery_recovery_exhausted": "⚠️ ویدیوی جلسه‌ات محفوظ است، اما تولید صوت یا متن پس از چند تلاش کامل نشد. فایل اصلی نگه داشته شده تا پشتیبانی مشکل را بررسی کند؛ اعتبارت دوباره کم نشده.",
        "large_video": "حجم ویدیو زیاده، برای همین توی {count} قسمت قابل پخش می‌فرستم.",
        "large_video_download": "🎥 فایل کامل جلسه آماده است.\n\n⬇️ دانلود یک‌تکه:\n{url}\n\nاین لینک تا {hours} ساعت معتبر است.",
        "large_audio_download": "🎧 فایل صوتی کامل جلسه آماده است.\n\n⬇️ دانلود فایل صوتی:\n{url}\n\nاین لینک تا {hours} ساعت معتبر است.",
        "video_part": "قسمت {index} از {count}",
        "payment_confirmed": "✅ ساعت ضبط شارژ شد؛ موجودی در /credits قابل مشاهده است.",
        "manual_mode_notice": "📩 فعلاً فقط ضبط با ارسال لینک جلسه فعال است. برای جلسه آینده، ایمیل رکوردر را به دعوت تقویم اضافه کن؛ برای جلسه در حال اجرا از «ورود فوری» استفاده کن.",
        "auto_unavailable": "⏸ قابلیت ضبط خودکار «همه جلسات» فعلاً فعال نیست و در پلن‌های فروشی ارائه نمی‌شود. برای ضبط، لینک هر جلسه را مستقیم در ربات بفرست.",
        "payment_scheduled": "✅ ساعت ضبط شارژ شد؛ ساعت‌های جدید فوری به موجودی اضافه شده‌اند.",
        "renewal_scheduled": "هر خرید فوری به کیف پول ساعت ضبط اضافه می‌شود.",
        "plan_rules_short": "هر خرید ساعت، بدون انقضا به موجودی اضافه می‌شود. نه اشتراک داریم، نه تمدید خودکار.",
        "payment_confirmed_legacy": "✅ پرداخت پلن قبلی {plan} تأیید شد. اعتبار تا {until} است؛ شرایط همان اشتراک قدیمی اعمال می‌شود.",
        "wallet_balance": "🎧 موجودی کل ساعت ضبط: {hours} ساعت و {minutes} دقیقه\n\nاعتبار انقضا ندارد؛ ساعت رایگان شروع و ساعت‌های خریداری‌شده در همین موجودی جمع می‌شن. مدت ضبط موفق جلسه از موجودی کم می‌شه.",
        "wallet_trial_included": "🎁 از این موجودی، {hours} ساعت و {minutes} دقیقه اعتبار رایگان شروع باقی مونده.",
        "wallet_empty": "⌛ موجودی ساعت ضبطت برای شروع جلسه جدید کافی نیست یا برای ضبط‌های در صف رزرو شده است. ساعت بیشتری شارژ کن.",
        "wallet_payment_confirmed": "✅ خرید {hours} ساعت ضبط موفق بود!\n⏱ موجودی کنونی: {balance_hours} ساعت و {balance_minutes} دقیقه.\n\nاعتبار تاریخ انقضا ندارد و هر خرید جدید به موجودی اضافه می‌شود.",
    },
    "en": {
        "language_choose": "🌐 Choose the bot language. Meeting language is independent and detected automatically.",
        "language_changed": "✅ Bot language changed to English.",
        "new_prompt": "Send the Google Meet link here. If it is on the calendar, I’ll join on time. If it has already started, use “⚡ Join now”.",
        "admin_ready": "The admin panel is ready 👇\n{url}\n\nThis link is valid for 15 minutes.",
        "admin_only": "This section is only available to the bot administrator 🙂",
        "premium_active": "⏱ Your BeOnMeet recording-hour balance\n\nPurchased hours do not expire and new purchases are added to your balance.",
        "premium_offer": "⏱ Buy BeOnMeet recording hours\n\nNo monthly subscriptions or plans: just prepaid recording time.\n\n• Each purchase adds to your existing balance immediately.\n• Purchased hours never expire.\n• Successfully recorded meeting time is deducted; if an ongoing meeting exceeds the available balance, excess time is deducted from your next top-up.\n• No automatic renewals or automatic overage charges.\n• Buy the same amount again any time to add more hours.\n\nAvailable recording-hour purchases:",
        "free_limit_reached": "⌛ Your free welcome recording time has run out. Top up recording hours to continue; purchased hours never expire.",
        "plan_monthly": "1 month · 198,000 toman",
        "plan_quarterly": "3 months · 499,000 toman",
        "plan_halfyear": "6 months · 799,000 toman",
        "plan_basic": "➕ Buy 2 recording hours · 298,000 toman",
        "plan_pro": "➕ Buy 6 recording hours · 498,000 toman",
        "plan_business": "➕ Buy 15 recording hours · 998,000 toman",
        "paid_quota_reached": "⏱ You do not have enough recording credit. Buy more hours any time and they will add to your balance.",
        "quota_remaining": "⏱ Recording credit balance: {minutes} minutes",
        "quota_legacy": "Your original legacy subscription rights remain active until their previously agreed expiry.",
        "sales_paused": "⏳ Recording-hour purchases are temporarily paused because this shared server is at its safety limit. Do not pay. Try /credits later.",
        "calendar_connected": "✅ Calendar connected",
        "calendar_disconnected": "⚠️ Calendar is not connected yet\n{url}",
        "auto_premium_only": "The All Meetings feature is temporarily disabled. Please send each meeting link separately.",
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
        "join_connecting": "🔄 Connecting to the browser and opening Google Meet. I have not entered the meeting yet; no recording credit has been used.",
        "join_still_unconfirmed": "⚠️ Admission is still not confirmed; I am retrying. No credit is deducted unless the meeting is recorded and delivered.",
        "join_guest_access_possible": "🚫 I still could not join. Google Meet may silently deny anonymous guests or third-party bots without presenting an Admit request. For a controlled test, the host can change Host controls → Meeting access to Open, which allows anyone with the link to join without approval. For customer sessions, an authenticated, invited Google account is safer. Recording has not started and no credit has been used.",
        "join_expired_without_recording": "⌛ This joining attempt did not begin recording within the allowed window and has been cleared from the bot’s active requests. If the meeting is still ongoing, you can submit its link again. No successful recording or credit deduction was registered for this request.",
        "join_already_processing": "⏳ A join attempt for this meeting is already processing. Please do not send the link again; I will notify you when admission or recording starts.",
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
        "delivery_recovery_exhausted": "⚠️ Your video is safe, but the separate audio or transcript could not be completed after repeated retries. The source is retained for support; your credit was not deducted again.",
        "large_video": "The video is large, so I’ll send it in {count} playable parts.",
        "large_video_download": "🎥 The full meeting recording is ready.\n\n⬇️ Download the complete file:\n{url}\n\nThis link is valid for {hours} hours.",
        "large_audio_download": "🎧 The full meeting audio is ready.\n\n⬇️ Download the audio file:\n{url}\n\nThis link is valid for {hours} hours.",
        "video_part": "Part {index} of {count}",
        "payment_confirmed": "✅ Your recording-hour credit was added. Check /credits.",
        "manual_mode_notice": "📩 Recording works by sending each meeting link. For scheduled meetings invite the recorder email to the event; for live meetings use Join now.",
        "auto_unavailable": "⏸ The All Meetings automatic-calendar feature is temporarily unavailable and is not part of current paid plans. Send each meeting link directly to this bot.",
        "payment_scheduled": "✅ Your recording-hour credit was added immediately.",
        "renewal_scheduled": "New purchases add hours to your wallet immediately.",
        "plan_rules_short": "Each purchase adds permanent recording hours to your balance. No subscriptions or auto-renewals.",
        "payment_confirmed_legacy": "✅ Your legacy plan {plan} payment was confirmed. Active until {until}; its original plan terms apply.",
        "wallet_balance": "🎧 Total recording credit: {hours} h {minutes} min\n\nWelcome credit and purchased hours are combined in this balance. Purchased hours never expire; completed recording time is deducted.",
        "wallet_trial_included": "🎁 This total includes {hours} h {minutes} min of remaining free welcome credit.",
        "wallet_empty": "⌛ You have too little recording credit to start another recording, or hours are reserved for ongoing/queued recordings. Top up to continue.",
        "wallet_payment_confirmed": "✅ You bought {hours} recording hours!\n⏱ Current credit: {balance_hours} h {balance_minutes} min.\n\nHours never expire and new purchases are added to your existing balance.",
    },
    "de": {
        "language_choose": "🌐 Wähle die Sprache des Bots. Die Sprache des Meetings ist davon unabhängig und wird automatisch erkannt.",
        "language_changed": "✅ Die Bot Sprache wurde auf Deutsch umgestellt.",
        "new_prompt": "Sende den Google Meet Link hier. Wenn der Termin im Kalender steht, trete ich pünktlich bei. Wenn er schon läuft, nutze „⚡ Sofort beitreten“.",
        "admin_ready": "Der Adminbereich ist bereit 👇\n{url}\n\nDieser Link ist 15 Minuten gültig.",
        "admin_only": "Dieser Bereich ist nur für den Bot Administrator verfügbar 🙂",
        "premium_active": "⏱ Dein Aufnahmezeitguthaben\n\nGekaufte Stunden verfallen nicht. Weitere Käufe erhöhen dein Guthaben.",
        "premium_offer": "⏱ BeOnMeet Aufnahmestunden kaufen\n\nKeine monatlichen Abos oder Tarife: nur im Voraus bezahlte Aufnahmezeit.\n\n• Jeder Kauf lädt dein Guthaben sofort auf.\n• Die gekauften Stunden verfallen nicht.\n• Die Dauer erfolgreich aufgenommener Meetings wird abgezogen; ein laufendes Meeting darf das Restguthaben überschreiten. Die zusätzliche Zeit wird bei der nächsten Aufladung verrechnet.\n• Keine automatische Verlängerung oder automatische Zusatzgebühr.\n• Du kannst jederzeit erneut Stunden kaufen.\n\nVerfügbare Mengen:",
        "free_limit_reached": "⌛ Dein kostenloses Startguthaben ist aufgebraucht. Lade weitere Aufnahmestunden auf; gekauftes Guthaben verfällt nicht.",
        "plan_monthly": "1 Monat · 198.000 Toman",
        "plan_quarterly": "3 Monate · 499.000 Toman",
        "plan_halfyear": "6 Monate · 799.000 Toman",
        "plan_basic": "➕ 2 Aufnahmestunden kaufen · 298.000 Toman",
        "plan_pro": "➕ 6 Aufnahmestunden kaufen · 498.000 Toman",
        "plan_business": "➕ 15 Aufnahmestunden kaufen · 998.000 Toman",
        "paid_quota_reached": "⏱ Dein Aufnahmeguthaben reicht nicht aus. Kaufe jederzeit weitere Stunden dazu.",
        "quota_remaining": "⏱ Aufnahmezeitguthaben: {minutes} Minuten",
        "quota_legacy": "Deine bestehenden alten Aborechte gelten bis zum bisherigen Ablaufdatum.",
        "sales_paused": "⏳ Der Stundenverkauf ist wegen der Kapazitätsgrenze dieses Servers vorübergehend pausiert. Bitte nicht bezahlen; /credits später erneut prüfen.",
        "calendar_connected": "✅ Kalender verbunden",
        "calendar_disconnected": "⚠️ Kalender ist noch nicht verbunden\n{url}",
        "auto_premium_only": "Alle Meetings ist derzeit deaktiviert. Bitte schicke jeden Meeting-Link einzeln.",
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
        "join_connecting": "🔄 Ich verbinde mich mit dem Browser und öffne Google Meet. Ich bin noch nicht im Meeting; es wurde keine Aufnahmezeit abgezogen.",
        "join_still_unconfirmed": "⚠️ Der Beitritt ist noch nicht bestätigt; ich versuche es erneut. Ohne erfolgreiche Aufnahme und Zustellung wird kein Guthaben abgezogen.",
        "join_guest_access_possible": "🚫 Ich konnte dem Meeting noch nicht beitreten. Google Meet kann anonyme Gäste oder Drittanbieter-Bots ohne sichtbare Admit-Anfrage automatisch ablehnen. Zum Test kann der Host unter Host controls → Meeting access Open wählen; damit darf jeder mit dem Link ohne Freigabe beitreten. Für Kundentermine ist ein angemeldetes und eingeladenes Google-Konto sicherer. Die Aufnahme hat nicht begonnen und es wurde kein Guthaben verbraucht.",
        "join_expired_without_recording": "⌛ Dieser Beitrittsversuch hat innerhalb des vorgesehenen Zeitfensters keine Aufnahme gestartet und wurde aus den aktiven Anfragen des Bots entfernt. Falls das Meeting noch läuft, kannst du den Link erneut senden. Für diese Anfrage wurde keine erfolgreiche Aufnahme oder Abbuchung erfasst.",
        "join_already_processing": "⏳ Für dieses Meeting läuft bereits ein Beitrittsversuch. Bitte sende den Link nicht erneut; ich melde mich, sobald ich zugelassen wurde oder die Aufnahme startet.",
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
        "delivery_recovery_exhausted": "⚠️ Dein Video ist gesichert, doch Audio oder Transkript konnten nicht fertiggestellt werden. Die Quelldatei bleibt für den Support erhalten; es wird kein Guthaben erneut abgezogen.",
        "large_video": "Das Video ist groß, daher sende ich es in {count} abspielbaren Teilen.",
        "large_video_download": "🎥 Die vollständige Meeting Aufnahme ist bereit.\n\n⬇️ Vollständige Datei herunterladen:\n{url}\n\nDieser Link ist {hours} Stunden gültig.",
        "large_audio_download": "🎧 Die vollständige Audiodatei des Meetings ist bereit.\n\n⬇️ Audiodatei herunterladen:\n{url}\n\nDieser Link ist {hours} Stunden gültig.",
        "video_part": "Teil {index} von {count}",
        "payment_confirmed": "✅ Aufnahmeguthaben hinzugefügt. Prüfe /credits.",
        "manual_mode_notice": "📩 Zur Aufnahme jeden Meeting-Link einzeln senden. Bei geplanten Meetings die Recorder-E-Mail zum Termin einladen; für laufende Meetings Sofort beitreten verwenden.",
        "auto_unavailable": "⏸ Die automatische Funktion Alle Meetings ist derzeit nicht verfügbar und nicht in den kostenpflichtigen Tarifen enthalten. Bitte Meeting-Links einzeln senden.",
        "payment_scheduled": "✅ Aufnahmestunden wurden sofort gutgeschrieben.",
        "renewal_scheduled": "Neue Käufe erhöhen dein Guthaben sofort.",
        "plan_rules_short": "Jeder Kauf lädt dauerhaft Aufnahmestunden auf. Keine Abos oder automatischen Verlängerungen.",
        "payment_confirmed_legacy": "✅ Zahlung des bisherigen Tarifs {plan} bestätigt. Gültig bis {until}; die ursprünglichen Tarifbedingungen gelten.",
        "wallet_balance": "🎧 Gesamtes Aufnahmeguthaben: {hours} Std. {minutes} Min.\n\nKostenlose Startminuten und gekaufte Stunden zählen zum selben Guthaben. Gekaufte Stunden verfallen nicht; abgeschlossene Aufnahmen werden abgezogen.",
        "wallet_trial_included": "🎁 Davon sind {hours} Std. {minutes} Min. kostenloses Startguthaben übrig.",
        "wallet_empty": "⌛ Dein Aufnahmeguthaben reicht nicht aus oder ist für laufende/gewartete Aufnahmen reserviert. Kaufe weitere Stunden.",
        "wallet_payment_confirmed": "✅ {hours} Aufnahmestunden gekauft!\n⏱ Aktuelles Guthaben: {balance_hours} Std. {balance_minutes} Min.\n\nStunden verfallen nicht; weitere Käufe erhöhen dein vorhandenes Guthaben.",
    },
}

PROFILE_TEXT = {
    "fa": {
        "description": "لینک Google Meet رو بفرست. سر وقت وارد جلسه می‌شم، ضبط می‌کنم و فایل رو همینجا می‌فرستم. متن جلسه چندزبانه است.",
        "short": "ضبط Google Meet با ارسال لینک و متن چندزبانه",
        "commands": {
            "start": "راهنمای استفاده",
            "credits": "خرید ساعت ضبط بدون انقضا و مشاهده اعتبار",
            "now": "ورود فوری به جلسه",
            "language": "تغییر زبان",
            "admin": "پنل مدیریت",
        },
    },
    "en": {
        "description": "Send a Google Meet link. I join on time, record it and send the file here. Multilingual transcription is supported.",
        "short": "Google Meet link recording and multilingual transcripts",
        "commands": {
            "start": "How to use BeOnMeet",
            "credits": "Buy non-expiring recording hours and check balance",
            "now": "Join a meeting now",
            "language": "Change language",
            "admin": "Admin panel",
        },
    },
    "de": {
        "description": "Sende einen Google Meet Link. Ich trete pünktlich bei, nehme auf und sende die Datei hier. Mehrsprachige Transkription ist verfügbar.",
        "short": "Google Meet Links aufnehmen und mehrsprachige Transkripte",
        "commands": {
            "start": "BeOnMeet verwenden",
            "credits": "Aufnahmestunden ohne Ablaufdatum kaufen und Guthaben prüfen",
            "now": "Sofort einem Meeting beitreten",
            "language": "Sprache ändern",
            "admin": "Adminbereich",
        },
    },
}


def normalize_language(value: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    value = (value or "").strip().lower().replace("_", "-")
    if value.startswith("fa") or value.startswith("per"):
        return "fa"
    if value.startswith("de"):
        return "de"
    if value.startswith("en"):
        return "en"
    return default if default in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def tr(language: str, key: str, **kwargs: Any) -> str:
    lang = normalize_language(language)
    template = MESSAGES.get(lang, MESSAGES[DEFAULT_LANGUAGE]).get(key)
    if template is None:
        template = MESSAGES[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs)


def menu(language: str) -> dict[str, str]:
    return MENU_LABELS[normalize_language(language)]


def profile(language: str) -> dict[str, Any]:
    return PROFILE_TEXT[normalize_language(language)]


BUTTON_ACTIONS: dict[str, str] = {}
for _lang, _labels in MENU_LABELS.items():
    BUTTON_ACTIONS[_labels["new"]] = "/new"
    BUTTON_ACTIONS[_labels["premium"]] = "/credits"
    BUTTON_ACTIONS[_labels["now"]] = "/now"
    BUTTON_ACTIONS[_labels["auto"]] = "/auto"
    BUTTON_ACTIONS[_labels["help"]] = "/start"
    BUTTON_ACTIONS[_labels["language"]] = "/language"
    BUTTON_ACTIONS[_labels["admin"]] = "/admin"

for _lang, _button in LANGUAGE_BUTTONS.items():
    BUTTON_ACTIONS[_button] = f"/setlanguage {_lang}"
