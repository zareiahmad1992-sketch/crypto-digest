#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst_forwarder.py — رصد و بازنشر هوشمند تحلیل‌های طلا، دلار، کریپتو و انس
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

# ═══════════════ لیست کانال‌های هدف شما ═══════════════
CHANNELS = [
    {
        "handle": "vebinar1404",
        "name": "وبینار آینده دلار، طلا و بیت‌کوین",
        "category": "🥇 طلا، دلار و ماکرو",
        "type": "public"
    },
    {
        "handle": "drarashamini",
        "name": "دکتر آرش امینی",
        "category": "💵 تحلیل اقتصاد کلان و ارز",
        "type": "public"
    },
    {
        "handle": "rtmyashtrader",
        "name": "آرش تریدر (Rhythm Trader)",
        "category": "📊 انس جهانی و فارکس",
        "type": "public"
    },
    {
        "handle": "bitfa",
        "name": "بیتفا (Bitfa)",
        "category": "💎 تحلیل تخصصی کریپتو",
        "type": "public"
    },
    {
        "handle": "hamyar_crypto",
        "name": "همیار کریپتو",
        "category": "📈 تکنیکال کریپتو",
        "type": "public"
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# کلمات کلیدی برای حذف تبلیغات و حفظ پست‌های خالص تحلیلی
AD_FILTER = re.compile(
    r"کد تخفیف|ثبت نام|تخفیف ویژه|پشتیبانی فروش|خرید پکیج|واریز و برداشت|ایر‌دراپ|airdrop|جایزه", re.I
)

def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)

def send_photo_post(token, chat_id, photo_url, caption):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption[:1024],
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending photo: {e}")
        return False

def send_text_post(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending text: {e}")
        return False

def clean_content(text):
    # حذف لینک‌های داخلی تلگرام و آیدی‌های اضافه
    text = re.sub(r"t\.me/\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    return text.strip()

def process_channel(chan, last_id, token, chat_id):
    handle = chan["handle"]
    url = f"https://t.me/s/{handle}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return last_id

        soup = BeautifulSoup(r.text, "html.parser")
        messages = soup.select(".tgme_widget_message")
        if not messages:
            return last_id

        newest_id = last_id

        for m in messages:
            post_id_raw = m.get("data-post", "").split("/")[-1]
            if not post_id_raw.isdigit():
                continue
            pid = int(post_id_raw)

            if pid <= last_id:
                continue

            if pid > newest_id:
                newest_id = pid

            text_elem = m.select_one(".tgme_widget_message_text")
            raw_text = text_elem.get_text("\n").strip() if text_elem else ""

            # رد کردن پست‌های تبلیغاتی
            if AD_FILTER.search(raw_text):
                continue

            # اگر نه متن تحلیلی دارد و نه عکس، رد شود
            photo_wrap = m.select_one(".tgme_widget_message_photo_wrap")
            if len(raw_text) < 25 and not photo_wrap:
                continue

            photo_url = None
            if photo_wrap and "background-image:url('" in photo_wrap.get("style", ""):
                photo_url = photo_wrap["style"].split("url('")[1].split("')")[0]

            cleaned = clean_content(raw_text)

            post_msg = f"""🎙 <b>تحلیل منتخب از {chan['name']}</b>
🏷 <b>دسته‌بندی:</b> {chan['category']}
━━━━━━━━━━━━━━━━━━━━
{cleaned}

🔗 <a href='https://t.me/{handle}/{pid}'>مشاهده پست در کانال اصلی</a>"""

            if photo_url:
                send_photo_post(token, chat_id, photo_url, post_msg)
            elif cleaned:
                send_text_post(token, chat_id, post_msg)

            print(f"✅ پست تحلیلی جدید از [{chan['name']}] ارسال شد.")
            time.sleep(1.5)

        return newest_id

    except Exception as e:
        print(f"Error scraping {handle}: {e}")
        return last_id

def main():
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("BOT_TOKEN / CHANNEL_ID is not set.")
        return

    state = load_state()
    updated = dict(state)

    for chan in CHANNELS:
        handle = chan["handle"]
        last_id = state.get(handle, 0)
        new_last_id = process_channel(chan, last_id, token, chat_id)
        updated[handle] = new_last_id

    save_state(updated)

if __name__ == "__main__":
    main()
