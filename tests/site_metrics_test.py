"""Exercise the public and authenticated routes against an isolated database."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from fastapi.testclient import TestClient

with TemporaryDirectory() as directory:
    os.environ.update(BEONMEET_DATA_DIR=directory, BEONMEET_DB_PATH=directory+"/app.db",
                      DATABASE_URL="", GOOGLE_CLIENT_ID="test", GOOGLE_CLIENT_SECRET="test",
                      TELEGRAM_BOT_TOKEN="test", ADMINUSER="100", INTERNAL_SECRET="local-tests-only")
    import admin_panel, landing_metrics, main
    admin_panel.init_db()
    client = TestClient(main.app, base_url="https://testserver")
    pages = [("/", "fa"), ("/fa","fa"), ("/en","en"), ("/privacy","fa"), ("/privacy-policy","fa"),
             ("/terms","fa"), ("/terms-of-service","fa"), ("/en/privacy","en"), ("/en/terms","en"),
             ("/docs","fa"), ("/redoc","fa"), ("/api/billing/payment-return","fa")]
    for url,lang in pages:
        result = client.get(url)
        assert result.status_code == 200 and f'lang="{lang}"' in result.text and "site.css" in result.text, url
        assert ("metrics.js" in result.text) == (url in ("/","/en","/fa"))
    html = {"Accept":"text/html"}
    for url, status in [("/missing",404),("/auth/google/callback?state=invalid",400),("/admin/analytics",401)]:
        result = client.get(url, headers=html)
        assert result.status_code == status and "site.css" in result.text
    assert client.get("/admin/analytics").status_code == 401
    url = "/api/landing/metrics"
    origin = {"Origin":"https://testserver"}
    event = dict(id="1"*32, lang="fa", seconds=0, depth=20, clicks={})
    assert client.post(url,json=event).status_code==403
    assert client.post(url,headers=origin,json={**event,"depth":140}).status_code==400
    assert client.post(url,headers=origin,json={**event,"clicks":{"anything":1}}).status_code==400
    def send(e):
        assert client.post(url,headers=origin,json=e).status_code==204
    send(event)
    update = {**event,"seconds":18,"depth":91,"clicks":{"header_start":1,"hero_start":2}}
    send(update)
    send(update)
    send(event)
    send({**event,"id":"2"*32,"lang":"en","seconds":6})
    summary, clicks, starts, daily = landing_metrics.report(1)
    assert summary=={"views":2,"fa":1,"seconds":24,"deep":1}
    assert clicks == {"hero_start":2,"header_start":1} and starts == 1 and sum(daily.values())==2
    login = urlsplit(admin_panel.make_admin_login_url())
    assert client.get(login.path+"?"+login.query, follow_redirects=False).status_code==302
    for url in ("/admin","/admin/users","/admin/plans","/admin/recordings","/admin/subscriptions","/admin/auto-meetings","/admin/analytics?days=1"):
        result = client.get(url)
        assert result.status_code==200 and 'class="admin-ui"' in result.text and "site.css" in result.text,url
    assert all(s in result.text for s in ("۵۰٫۰٪","۱۲ ثانیه","شروع در تلگرام · سربرگ"))
    assert client.get("/admin/analytics?days=2").status_code==400
print("SITE_LANGUAGE_ADMIN_ANALYTICS_PASS")
