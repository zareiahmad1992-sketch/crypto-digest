#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tracker.py — رصد لحظه‌ای معاملات فعال و ارسال هشدار ریسک‌فری و تارگت‌ها
"""
import os
import json
from pathlib import Path
import requests

POSITIONS_FILE = Path("data/active_positions.json")
BASE_URL = "https://fapi.binance.com"

def load_pos():
    if not POSITIONS_FILE.exists(): return {}
    try: return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except: return {}

def save_pos(p):
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = POSITIONS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(POSITIONS_FILE)

def send_msg(token, chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=12)
    except: pass

def check():
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id: return

    positions = load_pos()
    if not positions: return
    updated = dict(positions)

    for pair, pos in positions.items():
        try:
            r = requests.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": pair}, timeout=8)
            curr = float(r.json()["price"])
        except: continue

        d, entry, tp1, tp2, sl = pos["direction"], pos["entry"], pos["tp1"], pos["tp2"], pos["stop_loss"]
        st = pos.get("status", "OPEN")

        if st == "OPEN":
            if (d == 1 and curr >= tp1) or (d == -1 and curr <= tp1):
                p_pct = abs(tp1 - entry) / entry * 100
                msg = f"""🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{pos['symbol']}</b>
💰 <b>سود محقق‌شده:</b> <code>+{p_pct:.2f}%</code>

🛡 <b>دستور فوری مدیریت ریسک (حفظ سرمایه):</b>
• ۵۰٪ از پوزیشن را نقد و سیو سود کنید.
• حد ضرر را به نقطه ورود (<code>${entry:,.4f}</code>) منتقل کنید (<b>Risk-Free</b>).
#مدیریت_معامله #{pos['symbol']}"""
                send_msg(token, chat_id, msg)
                updated[pair]["status"] = "TP1_HIT"
                updated[pair]["stop_loss"] = entry
            elif (d == 1 and curr <= sl) or (d == -1 and curr >= sl):
                l_pct = abs(entry - sl) / entry * 100
                msg = f"""🛑 <b>[خروج در حد ضرر • پایبندی به دیسپلین]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{pos['symbol']}</b> | نتیجه: <code>-{l_pct:.2f}%</code>
⚖️ <i>سرمایه اصلی حفظ شد. منتظر تاییدیه مطمئن بعدی باشید.</i>
#حد_ضرر #{pos['symbol']}"""
                send_msg(token, chat_id, msg)
                del updated[pair]

        elif st == "TP1_HIT":
            if (d == 1 and curr >= tp2) or (d == -1 and curr <= tp2):
                p_pct = abs(tp2 - entry) / entry * 100
                msg = f"""🚀 🔥 <b>[تارگت نهایی تاچ شد • خروج با حداکثر سود]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{pos['symbol']}</b> | سود کامل: <code>+{p_pct:.2f}%</code>
✨ <i>معامله با موفقیت کامل بسته شد.</i>
#تارگت_نهایی #{pos['symbol']}"""
                send_msg(token, chat_id, msg)
                del updated[pair]
            elif (d == 1 and curr <= entry) or (d == -1 and curr >= entry):
                msg = f"""🛡 <b>[خروج در نقطه ورود (Risk-Free Exit)]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{pos['symbol']}</b>
معامله در نقطه ورود بسته شد (با ذخیره سود مرحله اول).
#ریسک_فری #{pos['symbol']}"""
                send_msg(token, chat_id, msg)
                del updated[pair]

    save_pos(updated)

if __name__ == "__main__":
    check()
