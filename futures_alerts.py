#!/usr/bin/env python3
"""
Futures Alerts Engine with Dynamic Top 40 Market Cap / Volume Scanner.
Two-Tier Alert System:
- Tier 1: Confirmed Trade Setup (Score >= 70) -> Entry, SL, TP1 (50% close + Risk-Free), TP2
- Tier 2: Market Radar / Setup Brewing (Score 60-69) -> Watchlist alert
"""

import os
import sys
import json
import time
import requests
import argparse
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
DATA_FILE = "data/active_positions.json"

FALLBACK_TOP_40 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
    "NEARUSDT", "TONUSDT", "APTUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT",
    "AAVEUSDT", "INJUSDT", "FETUSDT", "RENDERUSDT", "TIAUSDT",
    "SEIUSDT", "ARBUSDT", "OPUSDT", "POLUSDT", "FTMUSDT",
    "ICPUSDT", "XLMUSDT", "TRXUSDT", "ETCUSDT", "STXUSDT",
    "FILUSDT", "ATOMUSDT", "ONDOUSDT", "GALAUSDT", "PENDLEUSDT"
]

def send_telegram(text, parse_mode="HTML"):
    if not BOT_TOKEN or not CHANNEL_ID:
        print("[Preview Mode - Telegram Output]:")
        print(text)
        print("-" * 50)
        return True
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False

def get_top_40_symbols():
    """Dynamically fetches top 40 USDT futures pairs sorted by 24h volume."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            tickers = r.json()
            valid = []
            for t in tickers:
                sym = t.get("symbol", "")
                if sym.endswith("USDT") and not sym.startswith(("USDC", "FDUSD", "TUSD", "BUSD")):
                    vol = float(t.get("quoteVolume", 0))
                    valid.append((sym, vol))
            valid.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [s[0] for s in valid[:40]]
            if len(top_symbols) >= 30:
                return top_symbols
    except Exception as e:
        print(f"Dynamic symbol fetch warning: {e}, falling back to static 40")
    return FALLBACK_TOP_40

def get_klines(symbol, interval="1h", limit=100):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def get_funding_rate(symbol):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return float(r.json().get("lastFundingRate", 0.0))
    except Exception:
        pass
    return 0.0

def calc_indicators(klines):
    if len(klines) < 60:
        return None
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    
    def ema(series, period):
        alpha = 2 / (period + 1)
        res = [series[0]]
        for val in series[1:]:
            res.append(val * alpha + res[-1] * (1 - alpha))
        return res
    
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    ema200 = ema(closes, min(len(closes), 200))[-1] if len(closes) >= 50 else ema50
    
    # RSI 14
    gains, losses = [], []
    for i in range(1, 15):
        diff = closes[-i] - closes[-i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 0.0001
    rs = avg_gain / (avg_loss if avg_loss != 0 else 0.0001)
    rsi14 = 100 - (100 / (1 + rs))
    
    # ATR 14
    tr_list = []
    for i in range(1, 15):
        h, l, prev_c = highs[-i], lows[-i], closes[-i-1]
        tr_list.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr14 = sum(tr_list) / 14
    
    # MACD (12, 26, 9)
    ema12_arr = ema(closes, 12)
    ema26_arr = ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12_arr, ema26_arr)]
    signal_line = ema(macd_line, 9)
    hist = macd_line[-1] - signal_line[-1]
    prev_hist = macd_line[-2] - signal_line[-2]
    
    # Ichimoku Base Line (Kijun 26) & Conversion (Tenkan 9)
    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
    
    # RVol (Volume vs 20-candle average)
    avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1]
    rvol = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    
    return {
        "price": closes[-1],
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi14,
        "atr": atr14,
        "macd_hist": hist,
        "macd_hist_rising": hist > prev_hist,
        "tenkan": tenkan,
        "kijun": kijun,
        "rvol": rvol
    }

def analyze_symbol(symbol):
    klines_1h = get_klines(symbol, "1h", 100)
    if not klines_1h:
        return None
    ind = calc_indicators(klines_1h)
    if not ind:
        return None
    funding = get_funding_rate(symbol)
    price = ind["price"]
    
    # Bullish Confluences
    long_score = 0
    long_reasons = []
    if price > ind["ema200"]:
        long_score += 20; long_reasons.append("قیمت بالای EMA 200 (روند کلان صعودی)")
    if ind["ema20"] > ind["ema50"]:
        long_score += 15; long_reasons.append("کراس صعودی EMA 20/50")
    if ind["tenkan"] > ind["kijun"] and price > ind["kijun"]:
        long_score += 20; long_reasons.append("حمایت تنکان/کیجون ایچیموکو")
    if ind["macd_hist"] > 0 and ind["macd_hist_rising"]:
        long_score += 15; long_reasons.append("مومنتوم مثبت و افزایشی MACD")
    if 45 <= ind["rsi"] <= 65:
        long_score += 15; long_reasons.append(f"مومنتوم RSI متعادل و مستعد رشد ({ind['rsi']:.1f})")
    if ind["rvol"] >= 1.2:
        long_score += 15; long_reasons.append(f"حجم معاملاتی تاییدکننده (RVol: {ind['rvol']:.2f}x)")
    if funding <= 0.01:
        long_score += 10; long_reasons.append("عدم اشباع فاندینگ‌ریت لانگ")
        
    # Bearish Confluences
    short_score = 0
    short_reasons = []
    if price < ind["ema200"]:
        short_score += 20; short_reasons.append("قیمت زیر EMA 200 (روند کلان نزولی)")
    if ind["ema20"] < ind["ema50"]:
        short_score += 15; short_reasons.append("کراس نزولی EMA 20/50")
    if ind["tenkan"] < ind["kijun"] and price < ind["kijun"]:
        short_score += 20; short_reasons.append("فشار نزولی تنکان/کیجون ایچیموکو")
    if ind["macd_hist"] < 0 and not ind["macd_hist_rising"]:
        short_score += 15; short_reasons.append("مومنتوم منفی و کاهشی MACD")
    if 35 <= ind["rsi"] <= 55:
        short_score += 15; short_reasons.append(f"مومنتوم RSI مستعد ریزش ({ind['rsi']:.1f})")
    if ind["rvol"] >= 1.2:
        short_score += 15; short_reasons.append(f"حجم معاملاتی تاییدکننده (RVol: {ind['rvol']:.2f}x)")
    if funding >= -0.01:
        short_score += 10; short_reasons.append("عدم اشباع فاندینگ‌ریت شورت")
        
    direction = "LONG" if long_score >= short_score else "SHORT"
    final_score = max(long_score, short_score)
    reasons = long_reasons if direction == "LONG" else short_reasons
    
    return {
        "symbol": symbol,
        "direction": direction,
        "score": final_score,
        "price": price,
        "atr": ind["atr"],
        "reasons": reasons,
        "funding": funding,
        "rvol": ind["rvol"]
    }

def load_positions():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("positions", [])
        except Exception:
            pass
    return []

def save_positions(positions):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"positions": positions}, f, ensure_ascii=False, indent=2)

def track_open_positions():
    positions = load_positions()
    if not positions:
        return
    updated_positions = []
    
    for pos in positions:
        symbol = pos["symbol"]
        klines = get_klines(symbol, "1m", 1)
        if not klines:
            updated_positions.append(pos)
            continue
        cur_price = float(klines[-1][4])
        direction = pos["direction"]
        entry = pos["entry"]
        sl = pos["sl"]
        tp1 = pos["tp1"]
        tp2 = pos["tp2"]
        status = pos.get("status", "OPEN")
        
        # Long tracking
        if direction == "LONG":
            if cur_price >= tp2:
                msg = (
                    f"🚀 🔥 <b>[تارگت نهایی تاچ شد • خروج کامل]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"🟢 <b>جهت:</b> LONG 🟢\n"
                    f"🎯 <b>قیمت تارگت ۲:</b> <code>{tp2:,.4f}</code>\n"
                    f"💰 <b>سود کل پوزیشن:</b> <code>+{((tp2-entry)/entry)*100*pos.get('leverage',2):.1f}%</code>\n\n"
                    f"✅ این معامله با موفقیت کامل بسته شد.\n"
                    f"#مدیریت_معامله #{symbol}"
                )
                send_telegram(msg)
                continue
            elif cur_price >= tp1 and status == "OPEN":
                pos["status"] = "TP1_HIT"
                pos["sl"] = entry
                msg = (
                    f"🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"🟢 <b>جهت:</b> LONG\n"
                    f"🎯 <b>تارگت ۱:</b> <code>{tp1:,.4f}</code> (تاچ شد ✅)\n"
                    f"🛡 <b>اقدام الزامی:</b> ۵۰٪ معامله را ببندید و حد ضرر را دقیقاً روی نقطه ورود (<code>{entry:,.4f}</code>) بگذارید.\n\n"
                    f"🚀 <b>تارگت نهایی:</b> <code>{tp2:,.4f}</code>\n"
                    f"#مدیریت_معامله #ریسک_فری #{symbol}"
                )
                send_telegram(msg)
                updated_positions.append(pos)
                continue
            elif cur_price <= sl:
                loss_type = "ریسک‌فری (بدون ضرر)" if status == "TP1_HIT" else "حد ضرر فعال شد"
                msg = (
                    f"🛑 <b>[خروج از معامله • {loss_type}]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"📉 <b>قیمت خروج:</b> <code>{cur_price:,.4f}</code>\n"
                    f"🛡 <b>پایان معامله طبق اصل حفظ سرمایه.</b>\n"
                    f"#مدیریت_معامله #{symbol}"
                )
                send_telegram(msg)
                continue
            else:
                updated_positions.append(pos)
                
        # Short tracking
        elif direction == "SHORT":
            if cur_price <= tp2:
                msg = (
                    f"🚀 🔥 <b>[تارگت نهایی تاچ شد • خروج کامل]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"🔴 <b>جهت:</b> SHORT 🔴\n"
                    f"🎯 <b>قیمت تارگت ۲:</b> <code>{tp2:,.4f}</code>\n"
                    f"💰 <b>سود کل پوزیشن:</b> <code>+{((entry-tp2)/entry)*100*pos.get('leverage',2):.1f}%</code>\n\n"
                    f"✅ این معامله با موفقیت کامل بسته شد.\n"
                    f"#مدیریت_معامله #{symbol}"
                )
                send_telegram(msg)
                continue
            elif cur_price <= tp1 and status == "OPEN":
                pos["status"] = "TP1_HIT"
                pos["sl"] = entry
                msg = (
                    f"🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"🔴 <b>جهت:</b> SHORT\n"
                    f"🎯 <b>تارگت ۱:</b> <code>{tp1:,.4f}</code> (تاچ شد ✅)\n"
                    f"🛡 <b>اقدام الزامی:</b> ۵۰٪ معامله را ببندید و حد ضرر را روی نقطه ورود (<code>{entry:,.4f}</code>) بگذارید.\n\n"
                    f"🚀 <b>تارگت نهایی:</b> <code>{tp2:,.4f}</code>\n"
                    f"#مدیریت_معامله #ریسک_فری #{symbol}"
                )
                send_telegram(msg)
                updated_positions.append(pos)
                continue
            elif cur_price >= sl:
                loss_type = "ریسک‌فری (بدون ضرر)" if status == "TP1_HIT" else "حد ضرر فعال شد"
                msg = (
                    f"🛑 <b>[خروج از معامله • {loss_type}]</b>\n\n"
                    f"🔹 <b>نماد:</b> #{symbol}\n"
                    f"📉 <b>قیمت خروج:</b> <code>{cur_price:,.4f}</code>\n"
                    f"🛡 <b>پایان معامله طبق اصل حفظ سرمایه.</b>\n"
                    f"#مدیریت_معامله #{symbol}"
                )
                send_telegram(msg)
                continue
            else:
                updated_positions.append(pos)

    save_positions(updated_positions)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Print alerts without sending")
    args, _ = parser.parse_known_args()
    
    print("🔍 بررسی وضعیت پوزیشن‌های باز و ریسک‌فری...")
    track_open_positions()
    
    symbols = get_top_40_symbols()
    print(f"🚀 در حال اسکن دقیق {len(symbols)} ارز برتر و پرحجم بازار فیوچرز...")
    
    active_symbols = [p["symbol"] for p in load_positions()]
    
    for symbol in symbols:
        time.sleep(0.15) # Polite delay
        res = analyze_symbol(symbol)
        if not res:
            continue
        
        price = res["price"]
        atr = res["atr"]
        score = res["score"]
        direction = res["direction"]
        
        # 1. Tier 1: Confirmed Trade Setup (Score >= 70)
        if score >= 70:
            if symbol in active_symbols:
                continue
            risk = 1.5 * atr
            if direction == "LONG":
                sl = price - risk
                tp1 = price + (1.5 * risk)
                tp2 = price + (2.5 * risk)
                dir_emoji = "🟢 LONG 🟢"
            else:
                sl = price + risk
                tp1 = price - (1.5 * risk)
                tp2 = price - (2.5 * risk)
                dir_emoji = "🔴 SHORT 🔴"
                
            reasons_str = "\n".join([f"  ▫️ {r}" for r in res["reasons"][:4]])
            msg = (
                f"⚡️ 🎯 <b>[سیگنال قطعی • تاییدیه چندگانه]</b>\n\n"
                f"🔹 <b>جفت‌ارز:</b> #{symbol}\n"
                f"📊 <b>جهت معامله:</b> {dir_emoji}\n"
                f"⭐️ <b>امتیاز استراتژی:</b> <code>{score}/100</code>\n\n"
                f"📍 <b>نقطه ورود:</b> <code>{price:,.4f}</code>\n"
                f"🛑 <b>حد ضرر (SL):</b> <code>{sl:,.4f}</code>\n"
                f"🎯 <b>تارگت اول (TP1):</b> <code>{tp1:,.4f}</code> (سیو ۵۰٪ + ریسک‌فری)\n"
                f"🚀 <b>تارگت دوم (TP2):</b> <code>{tp2:,.4f}</code>\n\n"
                f"🔍 <b>دلایل ورود و تاییده‌ها:</b>\n{reasons_str}\n\n"
                f"⚖️ <b>اهرم پیشنهادی:</b> <code>2x - 3x</code> (حداکثر ۱ الی ۲ درصد ریسک سرمایه)\n"
                f"#سیگنال_معاملاتی #{symbol} #حفظ_سرمایه"
            )
            send_telegram(msg)
            
            positions = load_positions()
            positions.append({
                "symbol": symbol,
                "direction": direction,
                "entry": price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "status": "OPEN",
                "leverage": 2,
                "opened_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_positions(positions)
            active_symbols.append(symbol)
            time.sleep(1)

        # 2. Tier 2: Market Radar / Setup Brewing (Score 60-69)
        elif 60 <= score < 70:
            if symbol in active_symbols:
                continue
            dir_str = "صعودی (Long Watch)" if direction == "LONG" else "نزولی (Short Watch)"
            reasons_str = "\n".join([f"  ▫️ {r}" for r in res["reasons"][:3]])
            msg = (
                f"👁 📡 <b>[رادار بازار • موقعیت در حال شکل‌گیری]</b>\n\n"
                f"🔹 <b>جفت‌ارز:</b> #{symbol}\n"
                f"🔭 <b>جهت احتمالی:</b> {dir_str}\n"
                f"📈 <b>امتیاز آمادگی:</b> <code>{score}/100</code>\n"
                f"💲 <b>قیمت فعلی:</b> <code>{price:,.4f}</code>\n\n"
                f"🔍 <b>نشانه‌های اولیه:</b>\n{reasons_str}\n\n"
                f"⚠️ <i>این پیام هشدار واچ‌لیست است؛ تا صدور تاییدیه قطعی صبور باشید.</i>\n"
                f"#رادار_مارکت #{symbol} #تحت_نظر"
            )
            send_telegram(msg)
            time.sleep(1)

if __name__ == "__main__":
    main()
