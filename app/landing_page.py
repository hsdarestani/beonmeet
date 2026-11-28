"""English and Persian public landing pages."""
from html import escape
from pathlib import Path
from string import Template
import os
import re

from billing_policy import PUBLIC_PLANS, PUBLIC_PLAN_CODES

ASSETS = Path(__file__).with_name("landing_assets")
ICONS = (
    '<path d="m10 13 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 1 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(1 1)"/>',
    '<rect x="2" y="5" width="14" height="14" rx="4"/><path d="m16 10 6-4v12l-6-4"/>',
    '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
)
EN = dict(title="BeOnMeet | Record Google Meet in Telegram", context="Google Meet recording",
          headline="Meet now.", accent="Replay later.", intro="Send your Google Meet link to BeOnMeet. Get the recording in your Telegram chat when the meeting ends.",
          how="How it works", pricing="Recording hours", faq="Questions", start="Open Telegram",
          skip="Skip to content", nav="Main navigation", howtitle="From meeting link to recording.",
          pricetitle="Choose your recording hours.", creditintro="Top up once and use your hours across meetings. Your unused hours never expire.",
          billing="Only verified time from delivered recordings is deducted, up to your available balance.",
          faqtitle="Before you record", example="Delivery preview", sample="Meeting recording", preview="Illustration of a recording delivered to Telegram",
          terms="Terms of service", privacy="Privacy policy", hours="hours", unit="toman",
          steps=[("Send the link","Paste a Meet link into the Telegram bot and choose Join now."),
                 ("Admit the recorder","Let participants know you’re recording. If Meet asks, the host admits BeOnMeet."),
                 ("Get the recording","Open your Telegram chat for the video. Eligible plans also include audio and automatic transcription.")],
          qa=[("Can I schedule a recording?","Yes. Send the meeting link to the bot and invite the recorder email shown in Telegram to your calendar event. Joining depends on available capacity and host admission."),
              ("Where do I buy hours?","Open the bot and choose recording credit. Each one-time purchase adds hours to your existing balance. There is no automatic renewal."),
              ("How long are delivery files available?","Temporary delivery files may remain available for up to 72 hours. Save the files you want to keep."),
              ("How is Google data used?","Meeting links are used for the recordings you request. Existing Calendar permissions are read-only and can be revoked in your Google Account. Google user data is not sold or used for advertising or ad targeting.")])
FA = dict(title="BeOnMeet | ضبط گوگل میت در تلگرام", context="ضبط جلسه‌های گوگل میت",
          headline="الان جلسه داری؟", accent="بعداً مرورش کن.", intro="لینک گوگل میت را برای ربات BeOnMeet بفرست. بعد از جلسه، ویدیوی ضبط‌شده را در همان گفت‌وگوی تلگرام تحویل بگیر.",
          how="روش استفاده", pricing="ساعت‌های ضبط", faq="پرسش‌ها", start="شروع در تلگرام",
          skip="رفتن به محتوای اصلی", nav="فهرست اصلی", howtitle="از لینک جلسه تا فایل ضبط‌شده",
          pricetitle="چند ساعت ضبط نیاز داری؟", creditintro="اعتبار را یک‌بار بخر و بین جلسه‌ها تقسیم کن. ساعت‌های باقی‌مانده تاریخ انقضا ندارند.",
          billing="فقط مدت تأییدشدهٔ ضبط‌های تحویل‌شده از اعتبارت کم می‌شود، تا سقف موجودی.",
          faqtitle="پیش از شروع ضبط", example="نمونهٔ تحویل در تلگرام", sample="فایل ضبط جلسه", preview="نمایش نمونهٔ فایل ضبط جلسه",
          terms="شرایط استفاده", privacy="حریم خصوصی", hours="ساعت", unit="تومان",
          steps=[("لینک جلسه را بفرست","لینک گوگل میت را در گفت‌وگو با ربات بفرست و «ورود فوری» را انتخاب کن."),
                 ("ربات را وارد جلسه کن","با شرکت‌کننده‌ها برای ضبط هماهنگ کن. اگر گوگل میت اجازهٔ ورود خواست، میزبان ربات را تأیید می‌کند."),
                 ("فایل را تحویل بگیر","بعد از جلسه، ویدیو در تلگرام برایت ارسال می‌شود. در طرح‌های ویژه، فایل صوتی و متن خودکار هم در دسترس‌اند.")],
          qa=[("می‌توانم ضبط را از قبل هماهنگ کنم؟","بله. لینک را در ربات بفرست و ایمیل ضبط‌کننده را که ربات نمایش می‌دهد به رویداد تقویم دعوت کن. ورود به ظرفیت آزاد و پذیرش میزبان بستگی دارد."),
              ("ساعت ضبط را از کجا بخرم؟","داخل ربات تلگرام، بخش خرید اعتبار ضبط را باز کن. ساعت‌های خریداری‌شده به موجودی قبلی اضافه می‌شوند و تمدید خودکار ندارند."),
              ("فایل‌ها تا چه زمانی در دسترس‌اند؟","فایل‌های موقت تحویل ممکن است تا ۷۲ ساعت در دسترس باشند. فایل‌هایی را که می‌خواهی نگه داری، ذخیره کن."),
              ("از اطلاعات گوگل من چطور استفاده می‌شود؟","لینک جلسه برای ضبط‌هایی استفاده می‌شود که خودت درخواست می‌کنی. دسترسی‌های قبلی تقویم فقط خواندنی‌اند و از حساب گوگل قابل لغو هستند. داده‌های گوگل فروخته نمی‌شوند و کاربرد تبلیغاتی ندارند.")])

def render_landing(lang):
    fa = lang == "fa"
    copy = FA if fa else EN
    bot = os.environ.get("TELEGRAM_BOT_URL", "").strip()
    start = copy["start"]
    if not re.fullmatch(r"https://t\.me/[A-Za-z0-9_]+(?:\?start=[A-Za-z0-9_]+)?", bot):
        bot = "mailto:meetrecorderbot@gmail.com?subject=BeOnMeet%20access"
        start = "درخواست دسترسی" if fa else "Request access"
    def number(value):
        return f"{value:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")) if fa else f"{value:,}"
    cards = []
    for code in PUBLIC_PLAN_CODES:
        plan = PUBLIC_PLANS[code]
        cards.append(f'<article class="plan"><h3>{number(plan["quota_minutes"] // 60)} {copy["hours"]}</h3>'
                     f'<strong>{number(plan["price"])} <small>{copy["unit"]}</small></strong></article>')
    steps = []
    for (heading, body), icon in zip(copy["steps"], ICONS):
        steps.append(f'<article class="step"><div class="step-icon"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">{icon}</svg></div><h3>{heading}</h3><p>{body}</p></article>')
    qa = "".join(f"<details><summary>{q}</summary><p>{a}</p></details>" for q,a in copy["qa"])
    wave = "".join(f'<i style="--h:{n}px;--d:-{i % 7 / 10}s"></i>' for i,n in enumerate([6,10,5,13,9,16,7,12,4,8,14,10,6,12,8,4,9,14,6,3]))
    return Template((ASSETS / "page.html").read_text()).substitute({
        **copy, "lang":lang, "dir":"rtl" if fa else "ltr", "home":"/fa" if fa else "/",
        "alternate":"/" if fa else "/fa", "otherlang":"en" if fa else "fa",
        "language":"English" if fa else "فارسی", "bot":escape(bot), "start":start, "steps":"".join(steps),
        "plans":"".join(cards), "questions":qa, "wave":wave, "css":(ASSETS / "style.css").read_text(),
    })
