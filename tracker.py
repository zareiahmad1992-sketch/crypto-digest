#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tracker.py — رصد زنده موقعیت‌های باز، اعلام تارگت‌ها و اعمال ریسک‌فری (Risk-Free)
"""
import os
import json
import time
from pathlib import Path
import requests

POSITIONS_FILE = Path("data/active_positions.json")
BASE_URL = "https://fapi.binance.com"

def load_positions():
    if not POSITIONS_FILE.exists():
        return {}
    try:
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_positions(pos):
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = POSITIONS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(pos, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(POSITIONS_FILE)

def get_current_price(symbol):
    try:
        r = requests.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=8)
        return float(r.json()["price"])
    except Exception:
        return None

def send_alert(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=12)
    except Exception:
        pass

def track_open_trades():
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id:
        return

    positions = load_positions()
    if not positions:
        return

    updated_positions = dict(positions)

    for pair, pos in positions.items():
        curr_price = get_current_price(pair)
        if not curr_price:
            continue

        direction = pos["direction"] # 1: LONG, -1: SHORT
        entry = pos["entry"]
        tp1 = pos["tp1"]
        tp2 = pos["tp2"]
        sl = pos["stop_loss"]
        status = pos.get("status", "OPEN")

        # بررسی تارگت اول
        if status == "OPEN":
            hit_tp1 = (curr_price >= tp1) if direction == 1 else (curr_price <= tp1)
            hit_sl = (curr_price <= sl) if direction == 1 else (curr_price >= sl)

            if hit_tp1:
                profit_pct = abs(tp1 - entry) / entry * 100
                msg = f"""🎯 <b>تارگت اول تاچ شد! ({pos['symbol']})</b>
━━━━━━━━━━━━━━━━━━━━
💰 <b>سود محقق‌شده:</b> <code>+{profit_pct:.2f}%</code>
🛡 <b>اقدام فوری مدیریت ریسک:</b>
• ۵۰٪ از حجم پوزیشن را سیو سود کنید.
• حد ضرر (Stop Loss) را دقیقاً به قیمت ورود (<code>${entry:,.4f}</code>) منتقل کنید تا ریسک معامله <b>صفر (Risk-Free)</b> شود."""
                send_alert(token, chat_id, msg)
                updated_positions[pair]["status"] = "TP1_HIT"
                updated_positions[pair]["stop_loss"] = entry # انتقال استاپ به نقطه ورود
                continue

            elif hit_sl:
                loss_pct = abs(entry - sl) / entry * 100
                msg = f"""🛑 <b>خروج به دلیل حد ضرر ({pos['symbol']})</b>
━━━━━━━━━━━━━━━━━━━━
📉 <b>نتیجه:</b> <code>-{loss_pct:.2f}%</code>
⚖️ <i>حفظ اصل سرمایه اولویت اول است؛ معامله با دیسپلین بسته شد.</i>"""
                send_alert(token, chat_id, msg)
                del updated_positions[pair]
                continue

        # بررسی تارگت نهایی (TP2)
        elif status == "TP1_HIT":
            hit_tp2 = (curr_price >= tp2) if direction == 1 else (curr_price <= tp2)
            hit_be_stop = (curr_price <= entry) if direction == 1 else (curr_price >= entry)

            if hit_tp2:
                profit_pct = abs(tp2 - entry) / entry * 100
                msg = f"""🚀 <b>تارگت نهایی (TP2) با موفقیت کامل لمس شد! ({pos['symbol']})</b>
━━━━━━━━━━━━━━━━━━━━
🔥 <b>مجموع سود:</b> <code>+{profit_pct:.2f}%</code>
✨ <i>معامله با حداکثر ریوارد با موفقیت بسته شد.</i>"""
                send_alert(token, chat_id, msg)
                del updated_positions[pair]
                continue

            elif hit_be_stop:
                msg = f"""🛡 <b>خروج بدون ریسک (Risk-Free Exit) در {pos['symbol']}</b>
━━━━━━━━━━━━━━━━━━━━
معامله در نقطه ورود بسته شد (با حفظ ۵۰٪ سود مرحله اول)."""
                send_alert(token, chat_id, msg)
                del updated_positions[pair]
                continue

    save_positions(updated_positions)

if __name__ == "__main__":
    track_open_trades()
