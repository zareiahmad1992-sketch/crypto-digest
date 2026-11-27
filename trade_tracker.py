#!/usr/bin/env python3
"""
Trade Lifecycle Tracker & Result Reporter
- Checks every 1m candle HIGH/LOW since each trade was opened, so touches between cron runs are never missed.
- Conservative rule: if SL and TP are inside the same candle, SL is assumed first.
- Realized R = sum(fraction_closed * R_at_exit) minus round-trip cost (0.14%, same as backtest).
- 50% closes at TP1, remaining 50% runs to TP2 or to SL (moved to entry = risk-free).
- Time stop: trades open longer than MAX_HOLD_HOURS close at the last 1m close.
"""

import os
import json
import time
import argparse
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
POSITIONS_FILE = "data/active_positions.json"
HISTORY_FILE = "data/trade_history.json"
MAX_HOLD_HOURS = 72
ROUND_TRIP_COST = 0.0014
TP1_FRACTION = 0.5

REASON_LABEL = {
    "TP2": "🏆 تارگت نهایی (TP2) تاچ شد",
    "BE": "🛡 بعد از TP1 در نقطه ورود بسته شد (ریسک‌فری)",
    "SL": "🛑 حد ضرر فعال شد",
    "TIME": "⏱ خروج زمانی (بیش از ۷۲ ساعت باز بود)",
}
RESULT_BADGE = {
    "WIN": "✅ موفق",
    "BE": "🟡 خنثی / ریسک‌فری",
    "LOSS": "❌ ناموفق (استاپ)",
}

def send_telegram(text):
    if not BOT_TOKEN or not CHANNEL_ID:
        print("[Preview Mode - Telegram Output]:")
        print(text)
        print("-" * 50)
        return True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fmt(p):
    if p >= 100:
        d = 2
    elif p >= 1:
        d = 4
    elif p >= 0.01:
        d = 6
    else:
        d = 8
    return f"{p:,.{d}f}"

def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

def duration_str(opened, closed):
    mins = int((parse_utc(closed) - parse_utc(opened)).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return f"{h} ساعت و {m} دقیقه"

def risk_of(pos):
    return abs(pos["tp1"] - pos["entry"]) / 1.5

def r_mult(pos, price):
    sign = 1 if pos["direction"] == "LONG" else -1
    return sign * (price - pos["entry"]) / risk_of(pos)

def fetch_candles_since(symbol, start_ms):
    candles = []
    cursor = start_ms
    url = "https://fapi.binance.com/fapi/v1/klines"
    while True:
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": "1m", "startTime": cursor, "limit": 1000}, timeout=15)
            if r.status_code != 200:
                break
            batch = r.json()
        except Exception:
            break
        if not batch:
            break
        candles.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 60_000
    return candles

def finish(pos, exit_price, ts_ms, reason):
    remaining = (1 - TP1_FRACTION) if pos["status"] == "TP1_HIT" else 1.0
    gross_r = pos.get("realized_r", 0.0) + remaining * r_mult(pos, exit_price)
    cost_r = ROUND_TRIP_COST / (risk_of(pos) / pos["entry"])
    net_r = gross_r - cost_r
    if net_r > 0.05:
        result = "WIN"
    elif reason == "SL" or net_r < -0.05:
        result = "LOSS"
    else:
        result = "BE"
    return {
        "id": f"{pos['symbol']}-{pos['opened_at']}",
        "symbol": pos["symbol"],
        "direction": pos["direction"],
        "entry": pos["entry"],
        "exit": exit_price,
        "opened_at": pos["opened_at"],
        "closed_at": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "r": round(net_r, 2),
        "result": result,
    }

def tp1_message(pos):
    icon = "🟢 LONG" if pos["direction"] == "LONG" else "🔴 SHORT"
    return (
        f"🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>\n\n"
        f"🔹 <b>نماد:</b> #{pos['symbol']}  |  {icon}\n"
        f"🎯 <b>تارگت ۱:</b> <code>{fmt(pos['tp1'])}</code> (تاچ شد ✅)\n"
        f"🛡 <b>اقدام الزامی:</b> ۵۰٪ معامله را ببندید و حد ضرر را روی نقطه ورود "
        f"(<code>{fmt(pos['entry'])}</code>) بگذارید.\n"
        f"🚀 <b>تارگت نهایی:</b> <code>{fmt(pos['tp2'])}</code>\n"
        f"#مدیریت_معامله #ریسک_فری #{pos['symbol']}"
    )

def close_message(t, trades):
    total = len(trades)
    wins = sum(1 for x in trades if x["result"] == "WIN")
    losses = sum(1 for x in trades if x["result"] == "LOSS")
    be = total - wins - losses
    net = sum(x["r"] for x in trades)
    wr = (wins / total * 100) if total else 0
    icon = "🟢 LONG" if t["direction"] == "LONG" else "🔴 SHORT"
    return (
        f"🏁 <b>[گزارش بستن معامله • نتیجه نهایی]</b>\n\n"
        f"🔹 <b>نماد:</b> #{t['symbol']}  |  {icon}\n"
        f"📍 <b>ورود:</b> <code>{fmt(t['entry'])}</code>\n"
        f"🏁 <b>خروج:</b> <code>{fmt(t['exit'])}</code>\n"
        f"📝 <b>دلیل خروج:</b> {REASON_LABEL[t['reason']]}\n\n"
        f"{RESULT_BADGE[t['result']]}  ←  <b>{t['r']:+.2f}R</b> (خالص پس از کارمزد)\n"
        f"⏱ <b>مدت معامله:</b> {duration_str(t['opened_at'], t['closed_at'])}\n\n"
        f"📊 <b>آمار کل ربات:</b>\n"
        f"   • معاملات بسته‌شده: {total}\n"
        f"   • ✅ برد: {wins}  |  🟡 خنثی: {be}  |  ❌ باخت: {losses}\n"
        f"   • نرخ برد: {wr:.0f}%\n"
        f"   • بازده خالص کل: <b>{net:+.2f}R</b>\n\n"
        f"#گزارش_نتایج #{t['symbol']} #حفظ_سرمایه"
    )

def summary_message(trades, open_count):
    total = len(trades)
    if total == 0:
        return (
            f"📊 <b>[گزارش عملکرد ربات]</b>\n\n"
            f"هنوز معامله‌ای بسته نشده است.\n"
            f"🔓 معاملات باز: {open_count}"
        )
    wins = sum(1 for x in trades if x["result"] == "WIN")
    losses = sum(1 for x in trades if x["result"] == "LOSS")
    be = total - wins - losses
    net = sum(x["r"] for x in trades)
    avg = net / total
    wr = wins / total * 100
    last = trades[-5:]
    last_lines = "\n".join(
        f"   {RESULT_BADGE[x['result']].split()[0]} #{x['symbol']}  {x['r']:+.2f}R" for x in reversed(last)
    )
    return (
        f"📊 <b>[گزارش عملکرد ربات • خلاصه]</b>\n\n"
        f"📁 <b>معاملات بسته‌شده:</b> {total}\n"
        f"✅ برد: {wins}  |  🟡 خنثی: {be}  |  ❌ باخت: {losses}\n"
        f"🎯 <b>نرخ برد:</b> {wr:.0f}%\n"
        f"💰 <b>بازده خالص کل:</b> <b>{net:+.2f}R</b>\n"
        f"📈 <b>میانگین هر معامله:</b> {avg:+.2f}R\n"
        f"🔓 <b>معاملات باز الان:</b> {open_count}\n\n"
        f"🕘 <b>آخرین ۵ نتیجه:</b>\n{last_lines}\n\n"
        f"ℹ️ <i>R = واحد ریسک اولیه هر معامله. مثلاً +2R یعنی دو برابر ریسک اولیه سود، و -1R یعنی ضرر کامل حد ضرر.</i>\n"
        f"#گزارش_عملکرد #حفظ_سرمایه"
    )

def evaluate(pos, candles):
    events = []
    is_long = pos["direction"] == "LONG"
    for c in candles:
        ts = int(c[0])
        high = float(c[2])
        low = float(c[3])
        if pos["status"] == "OPEN":
            hit_sl = (low <= pos["sl"]) if is_long else (high >= pos["sl"])
            hit_tp1 = (high >= pos["tp1"]) if is_long else (low <= pos["tp1"])
            hit_tp2 = (high >= pos["tp2"]) if is_long else (low <= pos["tp2"])
            if hit_sl:
                return finish(pos, pos["sl"], ts, "SL"), events
            if hit_tp1:
                pos["realized_r"] = TP1_FRACTION * r_mult(pos, pos["tp1"])
                pos["status"] = "TP1_HIT"
                pos["sl"] = pos["entry"]
                events.append(tp1_message(pos))
                if hit_tp2:
                    return finish(pos, pos["tp2"], ts, "TP2"), events
        else:
            hit_sl = (low <= pos["sl"]) if is_long else (high >= pos["sl"])
            hit_tp2 = (high >= pos["tp2"]) if is_long else (low <= pos["tp2"])
            if hit_sl:
                return finish(pos, pos["entry"], ts, "BE"), events
            if hit_tp2:
                return finish(pos, pos["tp2"], ts, "TP2"), events
    return None, events

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Print without saving state")
    parser.add_argument("--summary", action="store_true", help="Send overall performance summary")
    args, _ = parser.parse_known_args()

    history = load_json(HISTORY_FILE, {"trades": []})
    data = load_json(POSITIONS_FILE, {"positions": []})

    if args.summary:
        send_telegram(summary_message(history["trades"], len(data.get("positions", []))))
        return

    now_ms = int(time.time() * 1000)
    positions = data.get("positions", [])
    print(f"🔍 بررسی {len(positions)} معامله باز...")
    still_open = []

    for pos in positions:
        opened_ms = int(parse_utc(pos["opened_at"]).timestamp() * 1000)
        candles = fetch_candles_since(pos["symbol"], opened_ms + 60_000)
        closed, events = evaluate(pos, candles)
        for ev in events:
            send_telegram(ev)
        if closed is None and candles and (now_ms - opened_ms) > MAX_HOLD_HOURS * 3600 * 1000:
            last = candles[-1]
            closed = finish(pos, float(last[4]), int(last[0]), "TIME")
        if closed:
            history["trades"].append(closed)
            send_telegram(close_message(closed, history["trades"]))
            print(f"✅ بسته شد: {closed['symbol']} | {closed['r']:+.2f}R | {closed['reason']}")
        else:
            still_open.append(pos)
        time.sleep(0.2)

    if args.preview:
        print("(preview mode: no state saved)")
        return

    data["positions"] = still_open
    save_json(POSITIONS_FILE, data)
    save_json(HISTORY_FILE, history)
    print(f"💾 وضعیت ذخیره شد. معاملات باز: {len(still_open)}")

if __name__ == "__main__":
    main()
