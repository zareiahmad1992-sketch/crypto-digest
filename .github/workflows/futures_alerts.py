#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
futures_alerts.py — اسکنر هوشمند با سیستم دو سطحی (سیگنال قطعی + رادار آماده‌باش)
"""
import os
import sys
import json
import time
from pathlib import Path
import trend_alerts as t

STATE_FILE = Path("data/scanner_state.json")
POSITIONS_FILE = Path("data/active_positions.json")

def load_json(path):
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return {}

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)

def format_confirmed_signal(d: dict) -> str:
    is_long = "BUY" in d["signal"]
    dir_title = "🟢 ورود لانگ / خرید (LONG)" if is_long else "🔴 ورود شورت / فروش (SHORT)"
    risk_pct = abs(d["price"] - d["stop_loss"]) / d["price"] * 100
    r1_pct = abs(d["tp1"] - d["price"]) / d["price"] * 100
    r2_pct = abs(d["tp2"] - d["price"]) / d["price"] * 100
    reasons_text = "\n".join([f"  • {r}" for r in d["reasons"]])

    return f"""⚡️ 🎯 <b>[سیگنال قطعی • تاییدیه چندگانه]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{d['symbol']}</b> | جهت: {dir_title}
📊 <b>قدرت تاییدیه:</b> <code>{d['score']}/100</code> | RSI: <code>{d['rsi']}</code> | حجم: <code>{d['rvol']}x</code>

💵 <b>قیمت ورود:</b> <code>${d['price']:,.4f}</code>
🛑 <b>حد ضرر قطعی:</b> <code>${d['stop_loss']:,.4f}</code> (<code>{risk_pct:.2f}%-</code>)
🎯 <b>تارگت اول (سیو سود):</b> <code>${d['tp1']:,.4f}</code> (<code>{r1_pct:.2f}%+</code>)
🚀 <b>تارگت نهایی:</b> <code>${d['tp2']:,.4f}</code> (<code>{r2_pct:.2f}%+</code>)

🔎 <b>دلایل ورود:</b>
{reasons_text}

⚖️ <b>مدیریت سرمایه:</b> اهرم پیشنهادی 2x یا 3x | حداکثر ریسک ۱٪
🔗 <a href='https://www.coinglass.com/LiquidationHeatMap/{d['symbol']}'>هیت‌مپ لیکوییدیشن (CoinGlass)</a>
#سیگنال_معاملاتی #{d['symbol']}"""

def format_radar_alert(d: dict) -> str:
    is_long = "BUY" in d["signal"]
    side = "صعودی (آماده لانگ)" if is_long else "نزولی (آماده شورت)"
    return f"""👁 📡 <b>[رادار بازار • موقعیت در حال شکل‌گیری]</b>
━━━━━━━━━━━━━━━━━━━━
ارز: <b>#{d['symbol']}</b> | فاز احتمالی: <b>{side}</b>
📊 <b>امتیاز اعتبارسنجی:</b> <code>{d['score']}/100</code> (در آستانه تایید قطعی)
💵 <b>قیمت فعلی:</b> <code>${d['price']:,.4f}</code> | RSI: <code>{d['rsi']}</code> | حجم: <code>{d['rvol']}x</code>

⚠️ <i>این سیگنال قطعی نیست؛ چارت را زیر نظر بگیرید تا در صورت شکست سطح یا تایید پول هوشمند ورود کنید.</i>
#رادار_مارکت #{d['symbol']}"""

def main():
    is_preview = "--preview" in sys.argv
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()

    if not is_preview and (not token or not chat_id):
        print("Missing BOT_TOKEN or CHANNEL_ID")
        return 1

    state = load_json(STATE_FILE)
    positions = load_json(POSITIONS_FILE)
    updated_state = dict(state)
    updated_positions = dict(positions)

    symbols = t.DEFAULT_SYMBOLS
    print(f"🚀 اسکن {len(symbols)} ارز با سیستم دو سطحی...")

    for pair in symbols:
        try:
            analysis = t.inspect_market_deep(pair)
            if not analysis:
                continue

            score = analysis["score"]
            signal = analysis["signal"]
            prev_sig = state.get(pair)

            # سطح ۱: سیگنال قطعی ورود (امتیاز >= 70)
            if score >= 70:
                if prev_sig != f"SIGNAL_{signal}":
                    msg = format_confirmed_signal(analysis)
                    if is_preview:
                        print(f"\n[CONFIRMED SIGNAL]\n{msg}\n")
                    else:
                        t.send_telegram(token, chat_id, msg)
                    
                    updated_state[pair] = f"SIGNAL_{signal}"
                    # ثبت برای رهگیری خودکار در tracker.py
                    updated_positions[pair] = {
                        "symbol": analysis["symbol"],
                        "direction": 1 if "BUY" in signal else -1,
                        "entry": analysis["price"],
                        "stop_loss": analysis["stop_loss"],
                        "tp1": analysis["tp1"],
                        "tp2": analysis["tp2"],
                        "status": "OPEN"
                    }
                    time.sleep(1.5)

            # سطح ۲: رادار بازار (امتیاز 60 تا 69)
            elif 60 <= score < 70:
                if prev_sig != f"RADAR_{signal}":
                    msg = format_radar_alert(analysis)
                    if is_preview:
                        print(f"\n[RADAR WATCH]\n{msg}\n")
                    else:
                        t.send_telegram(token, chat_id, msg)
                    updated_state[pair] = f"RADAR_{signal}"
                    time.sleep(1.5)

        except Exception as e:
            print(f"Error {pair}: {e}")

    if not is_preview:
        save_json(STATE_FILE, updated_state)
        save_json(POSITIONS_FILE, updated_positions)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
