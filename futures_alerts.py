#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
futures_alerts.py — اسکنر هوشمند بازار فیوچرز و اسپات
"""
import os
import sys
import json
import time
from pathlib import Path
import trend_alerts as t

STATE_FILE = Path("data/scanner_state.json")

def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".json.tmp")
    temp_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_file.replace(STATE_FILE)

def format_telegram_alert(d: dict) -> str:
    is_long = "BUY" in d["signal"]
    dir_title = "🟢 موقعیت لانگ / خرید (LONG)" if is_long else "🔴 موقعیت شورت / فروش (SHORT)"
    trade_type = "اسپات و فیوچرز" if is_long else "فقط فیوچرز (خروج از اسپات)"
    
    risk_pct = abs(d["price"] - d["stop_loss"]) / d["price"] * 100
    r1_pct = abs(d["tp1"] - d["price"]) / d["price"] * 100
    r2_pct = abs(d["tp2"] - d["price"]) / d["price"] * 100

    reasons_text = "\n".join([f"  • {r}" for r in d["reasons"]])

    msg = f"""💎 <b>سیگنال با تاییدیه چندگانه ({d['symbol']})</b>
━━━━━━━━━━━━━━━━━━━━
🎯 <b>جهت:</b> {dir_title}
🏷 <b>بازار هدف:</b> {trade_type}
📊 <b>امتیاز سیستم:</b> <code>{d['score']}/100</code> | RSI: <code>{d['rsi']}</code> | حجم: <code>{d['rvol']}x</code>

💵 <b>قیمت ورود:</b> <code>${d['price']:,.4f}</code>
🛑 <b>حد ضرر قطعی (SL):</b> <code>${d['stop_loss']:,.4f}</code> (<code>{risk_pct:.2f}%-</code>)
🎯 <b>تارگت اول (TP1):</b> <code>${d['tp1']:,.4f}</code> (<code>{r1_pct:.2f}%+</code>)
🚀 <b>تارگت دوم (TP2):</b> <code>${d['tp2']:,.4f}</code> (<code>{r2_pct:.2f}%+</code>)

🔎 <b>دلایل ورود و تایید تکنیکال:</b>
{reasons_text}
• فاندینگ ریت: <code>{d['funding']:+.4f}%</code>

⚖️ <b>دستورالعمل حفظ سرمایه:</b>
• حداکثر ریسک مجاز: ۱٪ از کل مارجین حساب.
• اهرم پیشنهادی: حداکثر <b>2x یا 3x</b> (اهرم بالا ممنوع ⛔️).
• پس از تاچ تارگت اول، استاپ به نقطه ورود منتقل شود (Risk-Free).
━━━━━━━━━━━━━━━━━━━━
🔗 <a href="https://www.coinglass.com/LiquidationHeatMap/{d['symbol']}">بررسی هیت‌مپ لیکوییدیشن (CoinGlass)</a>
⏰ <i>ترکیب تایم‌فریم ۴ساعته و ۱ساعته</i>"""
    return msg

def main():
    is_preview = "--preview" in sys.argv
    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()

    if not is_preview and (not token or not chat_id):
        print("خطا: BOT_TOKEN یا CHANNEL_ID تنظیم نشده است.")
        return 1

    state = load_state()
    updated_state = dict(state)
    symbols = t.DEFAULT_SYMBOLS

    print(f"🚀 در حال اسکن {len(symbols)} جفت‌ارز نقدشونده...")

    for pair in symbols:
        try:
            analysis = t.inspect_market_deep(pair)
            if not analysis:
                continue

            current_signal = analysis["signal"]
            prev_signal = state.get(pair)

            if prev_signal == current_signal:
                print(f"[{pair}] بدون تغییر روند (قبلاً ارسال شده).")
                continue

            msg = format_telegram_alert(analysis)

            if is_preview:
                print("\n" + "="*50)
                print(msg)
                print("="*50 + "\n")
                updated_state[pair] = current_signal
            else:
                ok = t.send_telegram(token, chat_id, msg)
                if ok:
                    print(f"✅ سیگنال {pair} با موفقیت به تلگرام فرستاده شد.")
                    updated_state[pair] = current_signal
                else:
                    print(f"❌ خطا در ارسال تلگرام {pair}")

            time.sleep(1)

        except Exception as e:
            print(f"خطا در جفت‌ارز {pair}: {e}")

    if not is_preview:
        save_state(updated_state)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
