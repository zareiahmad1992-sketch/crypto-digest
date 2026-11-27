#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst_forwarder.py — دریافت و فوروارد فوق‌سریع تحلیل‌های طلا، دلار، انس و کریپتو
"""
import os
import re
import sys
import json
import time
from datetime import datetime, timezone
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
    },
    {
        "handle": "drarashamini",
        "name": "دکتر آرش امینی",
        "tag": "#اقتصاد_کلان #بازار_ارز",
        "badge": "💵 📊 <b>[دیدگاه اقتصاد کلان و ارز]</b>",
    },
    {
        "handle": "rtmyashtrader",
        "name": "آرش تریدر (Rhythm Trader)",
        "tag": "#انس_جهانی #فارکس",
        "badge": "🥇 🌍 <b>[تحلیل انس طلا (XAUUSD) و فارکس]</b>",
    },
    {
        "handle": "bitfa",
        "name": "بیتفا (Bitfa)",
        "tag": "#تحلیل_کریپتو #بیت_کوین",
        "badge": "💎 📈 <b>[تحلیل تخصصی کریپتو]</b>",
    },
    {
        "handle": "hamyar_crypto",
        "name": "همیار کریپتو",
        "tag": "#تکنیکال_کریپتو",
        "badge": "💎 📊 <b>[تکنیکال و سناریوهای مارکت]</b>",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}
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

def check_channels():
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id: return

    state = load_state()
    updated = dict(state)
    now_ts = datetime.now(timezone.utc).timestamp()

    for ch in CHANNELS:
        handle = ch["handle"]
        last_id = state.get(handle, 0)
        # افزودن پارامتر تصادفی برای شکستن کش سرورهای تلگرام
        url = f"https://t.me/s/{handle}?t={int(time.time())}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            msgs = soup.select(".tgme_widget_message")
            newest = last_id

            for m in msgs:
                pid_raw = m.get("data-post", "").split("/")[-1]
                if not pid_raw.isdigit(): continue
                pid = int(pid_raw)

                # بار اول که اجرا می‌شود، فقط آخرین پست را ثبت کند و ۲۰۰ پست قبلی را یکجا اسپم نکند
                if last_id == 0:
                    newest = pid
                    continue

                if pid <= last_id: continue
                if pid > newest: newest = pid

                # بررسی تاریخ: پست‌های بیشتر از ۲۴ ساعت گذشته فرستاده نشوند
                tm_tag = m.select_one("time[datetime]")
                if tm_tag:
                    try:
                        post_time = datetime.fromisoformat(tm_tag["datetime"].replace("Z", "+00:00")).timestamp()
                        if now_ts - post_time > 86400: # بیش از ۲۴ ساعت گذشته
                            continue
                    except: pass

                txt = m.select_one(".tgme_widget_message_text")
                raw = txt.get_text("\n").strip() if txt else ""
                if AD_FILTER.search(raw): continue

                p_wrap = m.select_one(".tgme_widget_message_photo_wrap")
                if len(raw) < 15 and not p_wrap: continue

                p_url = None
                if p_wrap and "background-image:url('" in p_wrap.get("style", ""):
                    p_url = p_wrap["style"].split("url('")[1].split("')")[0]

                raw = re.sub(r"t\.me/\S+|@\w+", "", raw).strip()

                msg = f"""{ch['badge']}
━━━━━━━━━━━━━━━━━━━━
{raw}

🏷 <b>منبع:</b> {ch['name']}
🔗 <a href='https://t.me/{handle}/{pid}'>مشاهده پست اصلی</a>
{ch['tag']}"""

                send_post(token, chat_id, msg, p_url)
                print(f"✅ پست جدید فوروارد شد: {ch['name']} ({pid})")
                time.sleep(1.5)

            updated[handle] = newest
        except Exception as e:
            print(f"Error {handle}: {e}")

    save_state(updated)

if __name__ == "__main__":
    check_channels()
