"""Shared navigation for the public documents and transactional pages."""
from html import escape
from fastapi.responses import HTMLResponse

STYLESHEET = '<link rel="stylesheet" href="/landing/site.css?v=2">'
BRAND = '<span class="site-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>BeOnMeet'

def document(title, body, lang="fa", section=None, feedback=False):
    en = lang == "en"
    home = "/en" if en else "/"
    prefix = "/en" if en else ""
    alternate = ("/" if en else "/en/") + section if section else None
    switch = f'<a lang="{"fa" if en else "en"}" href="{alternate}">{"فارسی" if en else "English"}</a>' if alternate else ""
    privacy, terms = ("Privacy policy","Terms of service") if en else ("حریم خصوصی","شرایط استفاده")
    return f"""<!doctype html><html lang="{lang}" dir="{'ltr' if en else 'rtl'}"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | BeOnMeet</title>{STYLESHEET}</head>
    <body class="site-page"><header class="site-head"><div class="site-frame"><a class="site-brand" href="{home}">{BRAND}</a>
    <nav><a href="{home}#how">{'How it works' if en else 'روش استفاده'}</a>{switch}</nav></div></header>
    <main class="site-frame"><article class="{'feedback' if feedback else 'reader'}">{body}</article></main>
    <footer class="site-foot"><div class="site-frame"><b dir="ltr">BeOnMeet</b><nav><a href="{prefix}/privacy">{privacy}</a>
    <a href="{prefix}/terms">{terms}</a></nav></div></footer></body></html>"""

def message_page(title, text):
    return document(title, f'<h1>{escape(title)}</h1><p>{escape(text)}</p><a class="primary-link" href="/">بازگشت به صفحهٔ اصلی</a>', feedback=True)

CONTACT = '<a href="mailto:meetrecorderbot@gmail.com">meetrecorderbot@gmail.com</a>'
ANALYTICS_EN = """<h2>Landing page analytics</h2><p>We count page loads, button clicks, visible scroll depth and active reading time. A random identifier lasts for one page load. These measurements use no cookies and are not linked to your Telegram or Google account. The analytics database does not collect IP addresses or full URLs. The report covers the most recent 90 days.</p>"""
ANALYTICS_FA = """<h2>آمار بازدید لندینگ</h2><p>تعداد بازشدن صفحه، کلیک روی دکمه‌ها، میزان پیمایش و مدت حضور فعال را اندازه می‌گیریم. هر بار بازشدن صفحه یک شناسهٔ تصادفی جداگانه دارد. این آمار بدون کوکی ثبت می‌شود و به حساب تلگرام یا گوگل وصل نیست. نشانی IP و آدرس کامل صفحه در پایگاه آمار ذخیره نمی‌شود. گزارش ۹۰ روز اخیر در دسترس است.</p>"""
PRIVACY_FA = f"""<span class="eyebrow">تاریخ اجرا · ۶ اکتبر ۲۰۲۶</span><h1>حریم خصوصی</h1>
<p>این سیاست توضیح می‌دهد BeOnMeet هنگام استفاده از خدمات جلسه چه اطلاعاتی دریافت، استفاده، نگهداری و به اشتراک می‌گذارد.</p>
<h2>اطلاعاتی که پردازش می‌کنیم</h2><p>با اتصال تقویم گوگل، سرویس از طریق OAuth دسترسی فقط‌خواندنی به تقویم‌ها و رویدادهای در دسترس حساب می‌گیرد. این اطلاعات می‌تواند شامل شناسهٔ تقویم، زمان و وضعیت جلسه، لینک گوگل میت و پاسخ دعوت‌شدگان باشد. شناسهٔ تلگرام برای ارسال پیام و فایل، وضعیت سرویس و پرداخت، گزارش‌های عملیاتی و فایل ضبط درخواستی نیز پردازش می‌شوند.</p>
<h2>استفاده از داده‌های گوگل</h2><p>اطلاعات تقویم برای پیدا کردن جلسه‌های برنامه‌ریزی‌شده، تشخیص زمان ورود، کنار گذاشتن جلسه‌های لغوشده یا ردشده، جلوگیری از ورود تکراری و ارتباط درخواست با حساب تلگرام متصل به کار می‌رود. با این دسترسی رویدادهای تقویم ایجاد، ویرایش یا حذف نمی‌شوند.</p>
<h2>سیاست استفادهٔ محدود گوگل</h2><p>استفاده و انتقال اطلاعات دریافتی از APIهای گوگل تابع Google API Services User Data Policy و الزامات Limited Use است. داده‌های کاربران گوگل فروخته نمی‌شوند، برای تبلیغات و هدف‌گیری تبلیغاتی به کار نمی‌روند و برای تبلیغات در اختیار اشخاص ثالث قرار نمی‌گیرند.</p>
<h2>نگهداری و تحویل فایل</h2><p>اطلاعات مجوز اتصال تقویم در زیرساخت BeOnMeet با دسترسی محدود به سرویس نگهداری می‌شود. حداقل اطلاعات لازم برای صف‌بندی، جلوگیری از درخواست تکراری و تحویل قابل اتکا ممکن است حفظ شود. ضبط و فایل‌های حاصل برای تحویل به درخواست‌کننده پردازش می‌شوند. فایل موقت پس از مهلت تحویل منقضی می‌شود؛ بسته به طرح و نوع خروجی، دانلود فایل کامل ممکن است تا ۷۲ ساعت در دسترس باشد.</p>
{ANALYTICS_FA}
<h2>اشتراک‌گذاری اطلاعات</h2><p>اطلاعات تنها در حد نیاز برای اجرای سرویس، از جمله ارتباط با تقویم گوگل و ارسال پیام و فایل در تلگرام، یا بر اساس الزام قانونی افشا می‌شود. اطلاعات شخصی به فروش نمی‌رسد.</p>
<h2>کنترل دسترسی و حذف داده‌ها</h2><p>می‌توانید تشخیص خودکار جلسه را در ربات خاموش کنید و هر زمان مجوز BeOnMeet را از حساب گوگل پس بگیرید. لغو مجوز، خواندن‌های بعدی تقویم را متوقف می‌کند. برای حذف اطلاعات باقی‌ماندهٔ حساب به {CONTACT} پیام بدهید.</p>
<h2>مسئولیت ضبط</h2><p>قوانین محلی یا مقررات سازمان ممکن است برای ضبط جلسه شرایطی تعیین کنند. مسئولیت اطلاع‌رسانی و دریافت رضایت لازم از شرکت‌کننده‌ها با فردی است که ضبط را درخواست یا فعال می‌کند.</p>
<h2>امنیت و تغییرات سیاست</h2><p>برای حفاظت از مجوزها و داده‌های جلسه از کنترل دسترسی، جداسازی اجزای سرویس و تدابیر عملیاتی استفاده می‌کنیم. امنیت مطلق در اینترنت قابل تضمین نیست. در صورت تغییر مهم در رویه‌های حریم خصوصی یا استفاده از داده‌های گوگل، در موارد لازم این سیاست پیش از شروع استفادهٔ جدید به‌روز می‌شود.</p>
<h2>تماس</h2><p>پرسش‌های حریم خصوصی و درخواست‌های حذف را به {CONTACT} بفرستید.</p>"""
TERMS_FA = f"""<span class="eyebrow">تاریخ اجرا · ۶ اکتبر ۲۰۲۶</span><h1>شرایط استفاده</h1>
<p>با اتصال حساب یا درخواست ضبط، این شرایط استفاده از BeOnMeet را می‌پذیرید.</p>
<h2>خدمات ضبط</h2><p>لینک جلسهٔ گوگل میت را در تلگرام می‌فرستید و فایل ضبط را در تلگرام تحویل می‌گیرید. اجرای درخواست به ظرفیت آزاد و پذیرش ربات در جلسه بستگی دارد.</p>
<h2>مسئولیت‌های کاربر</h2><ul><li>باید اجازهٔ اتصال حساب گوگل را داشته باشید.</li><li>رعایت مقررات محل کار و قوانین جلسه و محل ضبط، از جمله اطلاع‌رسانی و دریافت رضایت لازم، بر عهدهٔ شماست.</li><li>استفاده برای نظارت غیرقانونی، آزار، دسترسی بدون مجوز یا فعالیت غیرقانونی مجاز نیست.</li></ul>
<h2>گوگل و تلگرام</h2><p>گوگل میت، تقویم گوگل و تلگرام سرویس‌های مستقل‌اند. BeOnMeet وابسته به گوگل یا تلگرام و مورد تأیید آن‌ها نیست. دسترسی و سیاست‌های این خدمات می‌تواند بر عملکرد ضبط اثر بگذارد.</p>
<h2>دسترسی به جلسه</h2><p>کنترل ورود، شرایط شبکه، اختلال سرویس‌های دیگر، محدودیت ظرفیت یا تنظیمات جلسه می‌تواند ضبط و تحویل را عقب بیندازد یا مانع آن شود. ممکن است میزبان لازم باشد ورود ربات را تأیید کند.</p>
<h2>اعتبار ساعت ضبط و فایل‌های موقت</h2><p>با خرید یک‌بارهٔ ۲، ۶ یا ۱۵ ساعت، اعتبار بدون انقضا بلافاصله به موجودی شما اضافه می‌شود. مدت تأییدشدهٔ ضبط تحویل‌شده تا سقف اعتبار کسر می‌شود. با پایان موجودی، ضبط جدید به شارژ نیاز دارد. تمدید و شارژ خودکار، موجودی منفی و هزینهٔ مصرف مازاد وجود ندارد.</p>
<p>ماندهٔ طرح‌های فعال یا پیش‌خریدشده به اعتبار بدون انقضا تبدیل می‌شود. زمان مصرف‌شده و منقضی‌شده برنمی‌گردد. دارندگان اشتراک قدیمی نامحدود، حقوق توافق‌شده را تا پایان تاریخ اصلی حفظ می‌کنند. مهلت دریافت فایل موقت از اعتبار ساعت ضبط جداست.</p>
<h2>حریم خصوصی</h2><p>روش استفاده از داده‌های شخصی و اطلاعات گوگل در <a href="/privacy">سیاست حریم خصوصی</a> آمده است.</p>
<h2>محدودیت دسترسی</h2><p>در صورت نیاز معقول برای حفاظت از سرویس یا دیگران، مقابله با تقلب و سوءاستفاده یا اجرای الزامات قانونی ممکن است دسترسی محدود شود.</p>
<h2>محدودیت تضمین</h2><p>خدمات بر اساس دسترسی موجود ارائه می‌شود. تا جایی که قانون اجازه می‌دهد، ورود، ضبط، تبدیل گفتار به متن و تحویل بی‌وقفه و بدون خطا برای همهٔ جلسات تضمین نمی‌شود.</p>
<h2>تماس</h2><p>پرسش‌های مربوط به این شرایط را به {CONTACT} بفرستید.</p>"""


def api_document(response, title):
    header = f'<header class="site-head" dir="rtl"><div class="site-frame"><a href="/" class="site-brand">{BRAND}</a><strong>{escape(title)}</strong></div></header>'
    content = response.body.decode().replace("<html>", '<html lang="fa">').replace("</head>", STYLESHEET + "</head>")
    content = content.replace("<body>", '<body class="site-page api-doc">' + header + '<main lang="en" dir="ltr">')
    return HTMLResponse(content.replace("</body>", "</main></body>"))
