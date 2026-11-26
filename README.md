# 🧭 سامانه هوشمند پایش، تحلیل و اسکنر مارکت‌های مالی (Crypto-Digest)

یک پلتفرم خودکار، بدون نیاز به سرور شخصی (Serverless مبتنی بر GitHub Actions) برای تحلیل چندلایه بازار کریپتو، طلا، سکه، دلار و فارکس با تمرکز حداکثری بر **«حفظ اصل سرمایه» (Capital Preservation)**.

---

## 🎯 فلسفه و سیر تکامل سیستم

### ۱. نقطه آغاز (سیستم اولیه):
* **مشکل سیستم اولیه:** اتکا به تقاطع ساده میانگین‌های متحرک (EMA 20/50 Cross) در یک تایم‌فریم و بررسی تنها ۲ نماد (BTC/TON). این روش در بازارهای خنثی (Range) مرتباً حد ضرر فعال می‌کرد.
* **فقدان داده‌های چندمنبعی:** اخبار و تحلیل‌ها به صورت گزینش‌نشده جمع‌آوری می‌شدند.

### ۲. تکامل و تغییرات نوین (نسخه فعلی):
* **استراتژی ورود ۶ لایه (Institutional Confluence):** سیگنال زمانی صادر می‌شود که حداقل ۴ فیلتر تاییدیه همزمان ثبت شود:
  1. ساختار ماکرو و روند ۴ ساعته (EMA 200 + ابر ایچیموکو).
  2. مومنتوم روند ۱ ساعته (EMA 20/50 + MACD Histogram).
  3. فیلتر اشباع هیجانی (RSI 14 دوره).
  4. ورود پول هوشمند بر مبنای حجم نسبی (RVol >= 1.25x).
  5. شکست ساختار معتبر (Market Structure BOS).
  6. فیلتر ضد اسکوئیز با فاندینگ ریت (CoinGlass Derivatives Data).
* **مدیریت سرمایه پویا:** محاسبه حد ضرر بر مبنای نوسان واقعی (ATR) با نسبت سود به زیان حداقل $1:2$ و اهرم کنترل‌شده (حداکثر $2x-3x$).
* **پایش خودکار معاملات (Auto-Tracker):** رصد پوزیشن‌ها و ارسال پیام خودکار «ریسک‌فری» به محض تاچ شدن تارگت اول.
* **رصد بازارهای چندگانه:** جداسازی گزارش‌های طلای داخلی، دلار، انس جهانی و کریپتو.

---

## 📂 ساختار فایل‌ها و معماری پروژه

```text
crypto-digest/
├── .github/workflows/           # اتوماسیون‌های ابری (GitHub Actions)
│   ├── daily-post.yml          # اجرای گزارش روزانه بازار (۸:۳۰ صبح ایران)
│   ├── futures-alerts.yml      # اجرای اسکنر فیوچرز (هر ۳۰ دقیقه)
│   └── analyst-tracker.yml     # بازنشر تحلیل‌ها و ترکر معاملات (هر ۲۰ دقیقه)
│
├── data/                       # پایگاه‌های داده محلی (JSON)
│   ├── scanner_state.json      # وضعیت آخرین سیگنال‌های صادرشده
│   ├── active_positions.json   # معاملات باز در حال رصد برای تارگت و ریسک‌فری
│   └── analysts_state.json     # شناسه آخرین پست‌های فورواردشده تحلیل‌گران
│
├── daily.py                    # موتور جمع‌آوری اخبار، آنچین، فاندینگ و گزارش روزانه
├── futures_alerts.py           # اسکنر زنده ۱۳ ارز پرحجم و صدور آلارم با ریسک به ریوارد
├── trend_alerts.py             # کتابخانه محاسبات ریاضی و اندیکاتورها (بدون وابستگی سنگین)
├── analyst_forwarder.py        # بازنشر و تفکیک تحلیلی طلا، سکه، دلار و انس
├── tracker.py                  # ناظر زنده معاملات باز و اعلام تارگت‌ها/خروج بدون ریسک
├── backtest_futures.py         # موتور بک‌تست‌گیری تاریخی با شبیه‌سازی کارمزد و اسلیپیج
└── README.md                   # مستندات کامل پروژه



📡 منابع داده‌ای متصل به سیستم
۱. مراجع خبری و داده‌های کلان جهانی (RSS & APIs):

    CoinDesk & The Block: اخبار تحلیلی و نهادی اقتصاد کلان.
    Cointelegraph & Decrypt: پوشش رویدادهای عمومی کریپتو.
    CoinGecko API: داده‌های دامیننس، ارزش کل بازار و تغییرات ۲۴ ساعته.
    Alternative.me API: شاخص ترس و طمع (Fear & Greed Index).

۲. مراجع آنچین و پول هوشمند (On-Chain & Smart Money):

    Lookonchain & Whale Alert: رصد تراکنش‌های کیف‌پول‌های بزرگ و نهنگ‌ها.
    CryptoQuant & Glassnode: داده‌های ورودی/خروجی صرافی‌ها و وضعیت ماینرها.
    CoinGlass: نقشه حرارتی لیکوییدیشن (Liquidation HeatMap) و فاندینگ ریت.

۳. کانال‌های تخصصی طلا، دلار، انس و کریپتو (Telegram Monitoring):

    وبینار آینده طلا و دلار (@vebinar1404): چشم‌انداز بازار طلا، سکه، حباب و دلار.
    دکتر آرش امینی (@drarashamini): تحلیل بنیادی و کلان بازارهای مالی و ارزی.
    آرش تریدر (@rtmyashtrader): تحلیل تکنیکال انس جهانی طلا (XAUUSD) و فارکس.
    بیتفا (@bitfa): تحلیل ساختاری و تکنیکال بیت‌کوین و آلت‌کوین‌ها.
    همیار کریپتو (@hamyar_crypto): دیدگاه‌های معاملاتی و سطوح مهم قیمت.
    ارزدیجیتال و میهن‌بلاک‌چین: مراجع معتبر پوشش رویدادهای بازار.

🎨 راهنمای هویت بصری پیام‌های کانال

برای نظم کانال، تمام پیام‌ها از این ساختار برچسب‌گذاری استفاده می‌کنند:

    ☕️ 🧭 [نبض صبحگاهی مارکت] ➔ #گزارش_روزانه
    ⚡️ 🎯 [سیگنال تایید چندگانه] ➔ #سیگنال_معاملاتی #ارز_مربوطه
    🛡 💰 [مدیریت معامله / ریسک‌فری] ➔ #مدیریت_ریسک #تارگت
    🪙 🇮🇷 [بازار داخلی • طلا، سکه و دلار] ➔ #طلای_ایران #دلار_آزاد
    🥇 🌍 [انس جهانی و بازار بین‌الملل] ➔ #انس_طلا #فارکس
    💎 🎙 [دیدگاه تحلیل‌گران منتخب] ➔ #تحلیل_تخصصی



---

### بخش چهارم: کدهای آپدیت‌شده با دسته‌بندی و ظاهر تفکیک‌شده

#### ۱. فایل `analyst_forwarder.py` (تشخیص هوشمند طلا، سکه، دلار و کریپتو):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst_forwarder.py — رصد و بازنشر هوشمند تحلیل‌های طلا، سکه، دلار، انس و کریپتو
با تم گرافیکی مجزا برای هر بازار
"""
import os
import re
import sys
import json
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

STATE_FILE = Path("data/analysts_state.json")

CHANNELS = [
    {
        "handle": "vebinar1404",
        "name": "وبینار آینده طلا و دلار",
        "tag": "#طلای_ایران #دلار_آزاد",
        "badge": "🪙 🇮🇷 <b>[تحلیل بازار داخل • طلا و دلار]</b>",
        "type": "gold_ir"
    },
    {
        "handle": "drarashamini",
        "name": "دکتر آرش امینی",
        "tag": "#اقتصاد_کلان #بازار_ارز",
        "badge": "💵 📊 <b>[دیدگاه اقتصاد کلان و ارز]</b>",
        "type": "macro"
    },
    {
        "handle": "rtmyashtrader",
        "name": "آرش تریدر (Rhythm Trader)",
        "tag": "#انس_جهانی #فارکس",
        "badge": "🥇 🌍 <b>[تحلیل انس طلا (XAUUSD) و فارکس]</b>",
        "type": "forex"
    },
    {
        "handle": "bitfa",
        "name": "بیتفا (Bitfa)",
        "tag": "#تحلیل_کریپتو #بیت_کوین",
        "badge": "💎 📈 <b>[تحلیل تخصصی کریپتو]</b>",
        "type": "crypto"
    },
    {
        "handle": "hamyar_crypto",
        "name": "همیار کریپتو",
        "tag": "#تکنیکال_کریپتو",
        "badge": "💎 📊 <b>[تکنیکال و سناریوهای مارکت]</b>",
        "type": "crypto"
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
AD_FILTER = re.compile(r"کد تخفیف|ثبت نام|تخفیف ویژه|خرید پکیج|واریز و برداشت|ایر‌دراپ|airdrop|پاداش", re.I)

def load_state():
    if not STATE_FILE.exists(): return {}
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except: return {}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)

def send_post(token, chat_id, text, photo_url=None):
    if photo_url:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        payload = {"chat_id": chat_id, "photo": photo_url, "caption": text[:1024], "parse_mode": "HTML"}
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code == 200
    except:
        return False

def process():
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id: return

    state = load_state()
    updated = dict(state)

    for ch in CHANNELS:
        handle = ch["handle"]
        last_id = state.get(handle, 0)
        try:
            r = requests.get(f"https://t.me/s/{handle}", headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            msgs = soup.select(".tgme_widget_message")
            newest = last_id

            for m in msgs:
                pid_raw = m.get("data-post", "").split("/")[-1]
                if not pid_raw.isdigit(): continue
                pid = int(pid_raw)
                if pid <= last_id: continue
                if pid > newest: newest = pid

                txt = m.select_one(".tgme_widget_message_text")
                raw = txt.get_text("\n").strip() if txt else ""
                if AD_FILTER.search(raw): continue

                p_wrap = m.select_one(".tgme_widget_message_photo_wrap")
                if len(raw) < 20 and not p_wrap: continue

                p_url = None
                if p_wrap and "background-image:url('" in p_wrap.get("style", ""):
                    p_url = p_wrap["style"].split("url('")[1].split("')")[0]

                raw = re.sub(r"t\.me/\S+|@\w+", "", raw).strip()

                msg = f"""{ch['badge']}
━━━━━━━━━━━━━━━━━━━━
{raw}

🏷 <b>منبع:</b> {ch['name']}
🔗 <a href='https://t.me/{handle}/{pid}'>مشاهده در کانال اصلی</a>
{ch['tag']}"""

                send_post(token, chat_id, msg, p_url)
                time.sleep(1.5)

            updated[handle] = newest
        except Exception as e:
            print(f"Error {handle}: {e}")

    save_state(updated)

if __name__ == "__main__":
    process()
