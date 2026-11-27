#!/usr/bin/env python3
"""
Futures Alerts Engine - XT.com Exchange Data Feed
Top 40 Pure Crypto Assets on XT Exchange.
Features:
- Native XT.com Futures & Spot Market Data Feed
- Multi-confluence Technical Scoring (EMA 20/50/200, Ichimoku, MACD, RSI, RVol, Funding)
- Tier 1: Confirmed Signals (Score >= 70) with dynamic price precision
- Tier 2: Compact Market Radar (Score 60-69) with 6h anti-spam cooldown
- Candle-by-candle Position Tracker (TP1 Risk-Free, TP2 Full Win, Stop-Loss)
- Automated Trade History Ledger & Performance Scoreboard
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
POSITIONS_FILE = "data/active_positions.json"
HISTORY_FILE = "data/trade_history.json"
COOLDOWN_FILE = "data/radar_cooldown.json"

# ۴۰ رمزارز برتر بازار در صرافی XT
TOP_40_CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
    "NEARUSDT", "TONUSDT", "APTUSDT", "SHIBUSDT", "PEPEUSDT",
    "WIFUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT",
    "AAVEUSDT", "INJUSDT", "FETUSDT", "RENDERUSDT", "TIAUSDT",
    "SEIUSDT", "ARBUSDT", "OPUSDT", "POLUSDT", "FTMUSDT",
    "ICPUSDT", "XLMUSDT", "TRXUSDT", "ETCUSDT", "STXUSDT",
    "FILUSDT", "ATOMUSDT", "ONDOUSDT", "GALAUSDT", "PENDLEUSDT"
]

PREVIEW_MODE = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json"
}

def fmt_price(p):
    """Dynamic decimal precision so low-priced coins never round SL/TP to entry."""
    if p is None:
        return "0"
    ap = abs(p)
    if ap == 0:
        return "0"
    if ap < 0.0001:
        return f"{p:.7f}"
    if ap < 0.01:
        return f"{p:.6f}"
    if ap < 1:
        return f"{p:.5f}"
    if ap < 100:
        return f"{p:.3f}"
    return f"{p:,.2f}"

def send_telegram(text, parse_mode="HTML"):
    if PREVIEW_MODE or not BOT_TOKEN or not CHANNEL_ID:
        print("[Preview Mode - Telegram Output]:")
        print(text)
        print("-" * 55)
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

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(path, data):
    if PREVIEW_MODE:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def to_xt_symbol(symbol):
    """Converts BTCUSDT -> btc_usdt for XT API."""
    clean = symbol.replace("1000", "").upper()
    if clean.endswith("USDT"):
        base = clean[:-4]
        return f"{base.lower()}_usdt"
    return symbol.lower()

def get_klines_xt(symbol, interval="1h", limit=100):
    """Fetches candlestick data from XT Exchange (Futures or Spot)."""
    xt_sym = to_xt_symbol(symbol)
    
    # 1. Try XT Futures API
    xt_futures_url = f"https://fapi.xt.com/future/market/v1/public/kline?symbol={xt_sym}&interval={interval}&limit={limit}"
    try:
        r = requests.get(xt_futures_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            res = data.get("result", [])
            if res and isinstance(res, list):
                klines = []
                for item in res:
                    if isinstance(item, dict):
                        # Format: {"t": ts, "o": open, "c": close, "h": high, "l": low, "v": vol}
                        t = item.get("t") or item.get("time") or 0
                        o = float(item.get("o") or item.get("open") or 0)
                        h = float(item.get("h") or item.get("high") or 0)
                        l = float(item.get("l") or item.get("low") or 0)
                        c = float(item.get("c") or item.get("close") or 0)
                        v = float(item.get("v") or item.get("vol") or item.get("volume") or 0)
                        klines.append([t, o, h, l, c, v])
                    elif isinstance(item, (list, tuple)) and len(item) >= 6:
                        klines.append([item[0], float(item[1]), float(item[2]), float(item[3]), float(item[4]), float(item[5])])
                if len(klines) >= 30:
                    klines.sort(key=lambda x: x[0])
                    return klines
    except Exception:
        pass

    # 2. Try XT Spot API (sapi.xt.com)
    xt_spot_url = f"https://sapi.xt.com/v4/public/kline?symbol={xt_sym}&interval={interval}&limit={limit}"
    try:
        r = requests.get(xt_spot_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            res = data.get("result", [])
            if res and isinstance(res, list):
                klines = []
                for item in res:
                    if isinstance(item, dict):
                        t = item.get("t", 0)
                        o = float(item.get("o", 0))
                        h = float(item.get("h", 0))
                        l = float(item.get("l", 0))
                        c = float(item.get("c", 0))
                        v = float(item.get("v", 0))
                        klines.append([t, o, h, l, c, v])
                if len(klines) >= 30:
                    klines.sort(key=lambda x: x[0])
                    return klines
    except Exception:
        pass

    # 3. Fallback: BinanceVision / Gate
    bv_sym = symbol.replace("1000", "")
    bv_url = f"https://data-api.binance.vision/api/v3/klines?symbol={bv_sym}&interval={interval}&limit={limit}"
    try:
        r = requests.get(bv_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            raw = r.json()
            return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in raw]
    except Exception:
        pass

    return []

def get_live_price(symbol):
    """Gets real-time price from XT or fallback."""
    xt_sym = to_xt_symbol(symbol)
    
    # Try XT Spot ticker
    try:
        url = f"https://sapi.xt.com/v4/public/ticker/price?symbol={xt_sym}"
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            res = r.json().get("result", {})
            if isinstance(res, dict) and "p" in res:
                return float(res["p"])
            elif isinstance(res, list) and res and "p" in res[0]:
                return float(res[0]["p"])
    except Exception:
        pass

    # Fallback to recent candle close
    k = get_klines_xt(symbol, "1m", 2)
    if k:
        return float(k[-1][4])
    return None

def get_funding_rate_xt(symbol):
    """Fetches funding rate from XT futures."""
    xt_sym = to_xt_symbol(symbol)
    url = f"https://fapi.xt.com/future/market/v1/public/contract/funding-rate?symbol={xt_sym}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            res = r.json().get("result", {})
            if isinstance(res, dict) and "fundingRate" in res:
                return float(res["fundingRate"])
    except Exception:
        pass
    return 0.0001

def calc_indicators(klines):
    if len(klines) < 50:
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
    
    # MACD
    ema12_arr = ema(closes, 12)
    ema26_arr = ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12_arr, ema26_arr)]
    signal_line = ema(macd_line, 9)
    hist = macd_line[-1] - signal_line[-1]
    prev_hist = macd_line[-2] - signal_line[-2]
    
    # Ichimoku Base / Conversion
    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
    
    # Relative Volume
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
    klines_1h = get_klines_xt(symbol, "1h", 100)
    if not klines_1h:
        return None
    ind = calc_indicators(klines_1h)
    if not ind:
        return None
    funding = get_funding_rate_xt(symbol)
    price = ind["price"]
    
    # Bullish Confluences
    long_score, long_reasons = 0, []
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
        long_score += 15; long_reasons.append(f"حجم تاییدکننده صرافی XT (RVol: {ind['rvol']:.2f}x)")
    if funding <= 0.01:
        long_score += 10; long_reasons.append("عدم اشباع فاندینگ‌ریت لانگ")
        
    # Bearish Confluences
    short_score, short_reasons = 0, []
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
        short_score += 15; short_reasons.append(f"حجم تاییدکننده صرافی XT (RVol: {ind['rvol']:.2f}x)")
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

def compute_stats(trades):
    total = len(trades)
    tp2_wins = sum(1 for t in trades if t.get("result") == "TP2_WIN")
    rf_wins = sum(1 for t in trades if t.get("result") == "TP1_RISKFREE")
    sl_losses = sum(1 for t in trades if t.get("result") == "SL_LOSS")
    wins = tp2_wins + rf_wins
    win_rate = (wins / total * 100) if total > 0 else 0.0
    net_pnl = sum(float(t.get("pnl_pct", 0.0)) for t in trades)
    return {
        "total": total,
        "wins": wins,
        "tp2_wins": tp2_wins,
        "rf_wins": rf_wins,
        "sl_losses": sl_losses,
        "win_rate": win_rate,
        "net_pnl": net_pnl
    }

def mini_scoreboard(trades):
    st = compute_stats(trades)
    if st["total"] == 0:
        return ""
    sign = "+" if st["net_pnl"] >= 0 else ""
    return (
        f"\n📊 <b>آمار کل تا این لحظه (صرافی XT):</b> "
        f"<code>{st['total']}</code> معامله | "
        f"✅ <code>{st['wins']}</code> موفق (<code>{st['win_rate']:.1f}%</code>) | "
        f"🛑 <code>{st['sl_losses']}</code> استاپ | "
        f"برآیند: <code>{sign}{st['net_pnl']:.2f}%</code>"
    )

def calc_pnl_pct(direction, entry, exit_price, leverage=2):
    if entry <= 0:
        return 0.0
    if direction == "LONG":
        return ((exit_price - entry) / entry) * 100.0 * leverage
    return ((entry - exit_price) / entry) * 100.0 * leverage

def record_closed_trade(history_data, pos, exit_price, result, pnl_pct):
    closed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    history_data.setdefault("trades", []).append({
        "symbol": pos["symbol"],
        "direction": pos["direction"],
        "entry": pos["entry"],
        "exit_price": exit_price,
        "result": result,
        "pnl_pct": round(pnl_pct, 2),
        "leverage": pos.get("leverage", 2),
        "opened_at": pos.get("opened_at", ""),
        "closed_at": closed_at
    })
    save_json(HISTORY_FILE, history_data)

def track_open_positions():
    pos_data = load_json(POSITIONS_FILE, {"positions": []})
    positions = pos_data.get("positions", [])
    if not positions:
        return
    history_data = load_json(HISTORY_FILE, {"trades": [], "last_report_date": ""})
    updated_positions = []
    
    for pos in positions:
        symbol = pos["symbol"]
        direction = pos["direction"]
        entry = float(pos["entry"])
        sl = float(pos["sl"])
        tp1 = float(pos["tp1"])
        tp2 = float(pos["tp2"])
        lev = float(pos.get("leverage", 2))
        status = pos.get("status", "OPEN")
        opened_ts = int(pos.get("opened_ts_ms", 0))
        
        klines = get_klines_xt(symbol, "1m", 25)
        if not klines:
            updated_positions.append(pos)
            continue
            
        closed = False
        for k in klines:
            k_time = int(k[0])
            if opened_ts and k_time < opened_ts:
                continue
            k_high = float(k[2])
            k_low = float(k[3])
            
            if direction == "LONG":
                if status == "OPEN" and k_low <= sl:
                    pnl = calc_pnl_pct("LONG", entry, sl, lev)
                    record_closed_trade(history_data, pos, sl, "SL_LOSS", pnl)
                    msg = (
                        f"🛑 ❌ <b>[حد ضرر فعال شد • خروج ایمن]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (LONG • صرافی XT)\n"
                        f"📍 <b>ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"📉 <b>قیمت خروج (SL):</b> <code>{fmt_price(sl)}</code>\n"
                        f"📊 <b>نتیجه (اهرم {int(lev)}x):</b> <code>{pnl:.2f}%</code>\n"
                        f"🛡 <i>خروج منظم طبق اصل حفظ سرمایه انجام شد.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #حد_ضرر #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
                if status == "OPEN" and k_high >= tp1:
                    status = "TP1_HIT"
                    pos["status"] = "TP1_HIT"
                    pos["sl"] = entry
                    sl = entry
                    tp1_pnl = calc_pnl_pct("LONG", entry, tp1, lev)
                    msg = (
                        f"🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (LONG 🟢 • XT)\n"
                        f"🎯 <b>تارگت ۱:</b> <code>{fmt_price(tp1)}</code> (تاچ شد ✅)\n"
                        f"💰 <b>سود ۵۰٪ اول (اهرم {int(lev)}x):</b> <code>+{tp1_pnl:.2f}%</code>\n"
                        f"🛡 <b>اقدام الزامی:</b> ۵۰٪ معامله را سیو سود کنید و حد ضرر را روی ورود (<code>{fmt_price(entry)}</code>) بگذارید.\n"
                        f"🚀 <b>تارگت نهایی:</b> <code>{fmt_price(tp2)}</code>\n\n"
                        f"#مدیریت_معامله #ریسک_فری #{symbol}"
                    )
                    send_telegram(msg)
                if status == "TP1_HIT" and k_high >= tp2:
                    pnl_tp1 = calc_pnl_pct("LONG", entry, tp1, lev)
                    pnl_tp2 = calc_pnl_pct("LONG", entry, tp2, lev)
                    combined_pnl = 0.5 * pnl_tp1 + 0.5 * pnl_tp2
                    record_closed_trade(history_data, pos, tp2, "TP2_WIN", combined_pnl)
                    msg = (
                        f"🚀 🔥 <b>[موفقیت کامل • تارگت نهایی تاچ شد]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (LONG 🟢 • XT)\n"
                        f"📍 <b>ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"🎯 <b>تارگت ۲:</b> <code>{fmt_price(tp2)}</code> (تاچ شد ✅)\n"
                        f"💰 <b>سود خالص کل پوزیشن (اهرم {int(lev)}x):</b> <code>+{combined_pnl:.2f}%</code>\n"
                        f"🏆 <i>معامله با موفقیت ۱۰۰٪ بسته شد.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #تارگت_نهایی #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
                if status == "TP1_HIT" and k_low <= sl:
                    pnl_tp1 = calc_pnl_pct("LONG", entry, tp1, lev)
                    combined_pnl = 0.5 * pnl_tp1
                    record_closed_trade(history_data, pos, entry, "TP1_RISKFREE", combined_pnl)
                    msg = (
                        f"🛡 ✅ <b>[خروج ریسک‌فری • بسته شدن با سود]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (LONG • XT)\n"
                        f"📍 <b>خروج نیمه دوم در نقطه ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"💰 <b>سود قطعی ثبت‌شده (از ۵۰٪ تارگت ۱):</b> <code>+{combined_pnl:.2f}%</code>\n"
                        f"✅ <i>اصل سرمایه کاملاً حفظ شد و معامله با سود به پایان رسید.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #ریسک_فری #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
            elif direction == "SHORT":
                if status == "OPEN" and k_high >= sl:
                    pnl = calc_pnl_pct("SHORT", entry, sl, lev)
                    record_closed_trade(history_data, pos, sl, "SL_LOSS", pnl)
                    msg = (
                        f"🛑 ❌ <b>[حد ضرر فعال شد • خروج ایمن]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (SHORT • صرافی XT)\n"
                        f"📍 <b>ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"📈 <b>قیمت خروج (SL):</b> <code>{fmt_price(sl)}</code>\n"
                        f"📊 <b>نتیجه (اهرم {int(lev)}x):</b> <code>{pnl:.2f}%</code>\n"
                        f"🛡 <i>خروج منظم طبق اصل حفظ سرمایه انجام شد.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #حد_ضرر #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
                if status == "OPEN" and k_low <= tp1:
                    status = "TP1_HIT"
                    pos["status"] = "TP1_HIT"
                    pos["sl"] = entry
                    sl = entry
                    tp1_pnl = calc_pnl_pct("SHORT", entry, tp1, lev)
                    msg = (
                        f"🎯 🛡 <b>[تارگت اول تاچ شد • سیو سود و ریسک‌فری]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (SHORT 🔴 • XT)\n"
                        f"🎯 <b>تارگت ۱:</b> <code>{fmt_price(tp1)}</code> (تاچ شد ✅)\n"
                        f"💰 <b>سود ۵۰٪ اول (اهرم {int(lev)}x):</b> <code>+{tp1_pnl:.2f}%</code>\n"
                        f"🛡 <b>اقدام الزامی:</b> ۵۰٪ معامله را سیو سود کنید و حد ضرر را روی ورود (<code>{fmt_price(entry)}</code>) بگذارید.\n"
                        f"🚀 <b>تارگت نهایی:</b> <code>{fmt_price(tp2)}</code>\n\n"
                        f"#مدیریت_معامله #ریسک_فری #{symbol}"
                    )
                    send_telegram(msg)
                if status == "TP1_HIT" and k_low <= tp2:
                    pnl_tp1 = calc_pnl_pct("SHORT", entry, tp1, lev)
                    pnl_tp2 = calc_pnl_pct("SHORT", entry, tp2, lev)
                    combined_pnl = 0.5 * pnl_tp1 + 0.5 * pnl_tp2
                    record_closed_trade(history_data, pos, tp2, "TP2_WIN", combined_pnl)
                    msg = (
                        f"🚀 🔥 <b>[موفقیت کامل • تارگت نهایی تاچ شد]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (SHORT 🔴 • XT)\n"
                        f"📍 <b>ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"🎯 <b>تارگت ۲:</b> <code>{fmt_price(tp2)}</code> (تاچ شد ✅)\n"
                        f"💰 <b>سود خالص کل پوزیشن (اهرم {int(lev)}x):</b> <code>+{combined_pnl:.2f}%</code>\n"
                        f"🏆 <i>معامله با موفقیت ۱۰۰٪ بسته شد.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #تارگت_نهایی #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
                if status == "TP1_HIT" and k_high >= sl:
                    pnl_tp1 = calc_pnl_pct("SHORT", entry, tp1, lev)
                    combined_pnl = 0.5 * pnl_tp1
                    record_closed_trade(history_data, pos, entry, "TP1_RISKFREE", combined_pnl)
                    msg = (
                        f"🛡 ✅ <b>[خروج ریسک‌فری • بسته شدن با سود]</b>\n\n"
                        f"🔹 <b>نماد:</b> #{symbol} (SHORT • XT)\n"
                        f"📍 <b>خروج نیمه دوم در نقطه ورود:</b> <code>{fmt_price(entry)}</code>\n"
                        f"💰 <b>سود قطعی ثبت‌شده (از ۵۰٪ تارگت ۱):</b> <code>+{combined_pnl:.2f}%</code>\n"
                        f"✅ <i>اصل سرمایه کاملاً حفظ شد و معامله با سود به پایان رسید.</i>"
                        f"{mini_scoreboard(history_data['trades'])}\n\n"
                        f"#گزارش_معامله #ریسک_فری #{symbol}"
                    )
                    send_telegram(msg)
                    closed = True
                    break
        if not closed:
            updated_positions.append(pos)
    save_json(POSITIONS_FILE, {"positions": updated_positions})

def send_performance_report(force=False):
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    history_data = load_json(HISTORY_FILE, {"trades": [], "last_report_date": ""})
    pos_data = load_json(POSITIONS_FILE, {"positions": []})
    
    if not force:
        if history_data.get("last_report_date") == today_str or now_utc.hour < 18:
            return
            
    trades = history_data.get("trades", [])
    positions = pos_data.get("positions", [])
    if not force and not trades and not positions:
        return
        
    st = compute_stats(trades)
    sign = "+" if st["net_pnl"] >= 0 else ""
    
    recent_lines = []
    for t in trades[-5:]:
        res_icon = "🚀" if t["result"] == "TP2_WIN" else ("🛡" if t["result"] == "TP1_RISKFREE" else "🛑")
        p_sign = "+" if t["pnl_pct"] >= 0 else ""
        recent_lines.append(f"  {res_icon} #{t['symbol']} ({t['direction']}): <code>{p_sign}{t['pnl_pct']:.2f}%</code>")
        
    open_lines = []
    for p in positions:
        live = get_live_price(p["symbol"])
        if live:
            fl_pnl = calc_pnl_pct(p["direction"], float(p["entry"]), live, float(p.get("leverage", 2)))
            f_sign = "+" if fl_pnl >= 0 else ""
            st_badge = "🛡 ریسک‌فری" if p.get("status") == "TP1_HIT" else "⏳ باز"
            open_lines.append(
                f"  ▫️ #{p['symbol']} ({p['direction']}) | {st_badge} | شناور: <code>{f_sign}{fl_pnl:.2f}%</code>"
            )
            
    msg = (
        f"📊 🏆 <b>[کارنامه شفاف عملکرد ربات • صرافی XT]</b>\n\n"
        f"📈 <b>آمار کل معاملات بسته‌شده:</b> <code>{st['total']}</code>\n"
        f"  🚀 موفقیت کامل (TP2): <code>{st['tp2_wins']}</code>\n"
        f"  🛡 سود + ریسک‌فری (TP1): <code>{st['rf_wins']}</code>\n"
        f"  🛑 حد ضرر (SL): <code>{st['sl_losses']}</code>\n\n"
        f"🎯 <b>نرخ موفقیت (Win Rate):</b> <code>{st['win_rate']:.1f}%</code>\n"
        f"💰 <b>برآیند خالص (با اهرم 2x):</b> <code>{sign}{st['net_pnl']:.2f}%</code>\n"
    )
    if recent_lines:
        msg += "\n🧾 <b>آخرین معاملات بسته‌شده:</b>\n" + "\n".join(recent_lines) + "\n"
    if open_lines:
        msg += f"\n📡 <b>معاملات باز فعلی ({len(open_lines)}):</b>\n" + "\n".join(open_lines) + "\n"
    else:
        msg += "\n📡 <b>معاملات باز فعلی:</b> <i>در انتظار موقعیت کم‌ریسک جدید</i>\n"
    msg += "\n#کارنامه_عملکرد #صرافی_XT #حفظ_سرمایه"
    
    if send_telegram(msg):
        history_data["last_report_date"] = today_str
        save_json(HISTORY_FILE, history_data)

def main():
    global PREVIEW_MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Print output without sending or mutating state")
    parser.add_argument("--report", action="store_true", help="Force print/send performance report")
    args, _ = parser.parse_known_args()
    PREVIEW_MODE = args.preview

    if args.report:
        send_performance_report(force=True)
        return

    print("🔍 بررسی دقیق پوزیشن‌های باز بر اساس کندل‌های صرافی XT...")
    track_open_positions()
    send_performance_report(force=False)

    print(f"🚀 در حال اسکن دقیق {len(TOP_40_CRYPTO_SYMBOLS)} ارز برتر از صرافی XT...")
    pos_data = load_json(POSITIONS_FILE, {"positions": []})
    positions = pos_data.get("positions", [])
    active_symbols = [p["symbol"] for p in positions]
    cooldowns = load_json(COOLDOWN_FILE, {})
    now_ts = time.time()
    radar_candidates = []

    for symbol in TOP_40_CRYPTO_SYMBOLS:
        time.sleep(0.06)
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
                f"🔹 <b>جفت‌ارز:</b> #{symbol} (صرافی XT)\n"
                f"📊 <b>جهت معامله:</b> {dir_emoji}\n"
                f"⭐️ <b>امتیاز استراتژی:</b> <code>{score}/100</code>\n\n"
                f"📍 <b>نقطه ورود:</b> <code>{fmt_price(price)}</code>\n"
                f"🛑 <b>حد ضرر (SL):</b> <code>{fmt_price(sl)}</code>\n"
                f"🎯 <b>تارگت اول (TP1):</b> <code>{fmt_price(tp1)}</code> (سیو ۵۰٪ + ریسک‌فری)\n"
                f"🚀 <b>تارگت دوم (TP2):</b> <code>{fmt_price(tp2)}</code>\n\n"
                f"🔍 <b>دلایل ورود و تاییده‌ها:</b>\n{reasons_str}\n\n"
                f"⚖️ <b>اهرم پیشنهادی:</b> <code>2x - 3x</code> (حداکثر ۱ الی ۲ درصد ریسک سرمایه)\n"
                f"📡 <i>وضعیت این معامله تا رسیدن به تارگت یا حد ضرر به صورت خودکار گزارش خواهد شد.</i>\n"
                f"#سیگنال_معاملاتی #{symbol} #حفظ_سرمایه"
            )
            if send_telegram(msg):
                positions.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry": price,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "status": "OPEN",
                    "leverage": 2,
                    "opened_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "opened_ts_ms": int(time.time() * 1000)
                })
                active_symbols.append(symbol)
                save_json(POSITIONS_FILE, {"positions": positions})
                time.sleep(1)

        # 2. Tier 2: Market Radar / Setup Brewing (Score 60-69)
        elif 60 <= score < 70:
            if symbol in active_symbols:
                continue
            last_alert = float(cooldowns.get(symbol, 0))
            if now_ts - last_alert >= 6 * 3600:
                radar_candidates.append(res)

    if radar_candidates:
        radar_candidates.sort(key=lambda x: x["score"], reverse=True)
        top_radars = radar_candidates[:5]
        lines = []
        for r in top_radars:
            d_icon = "🟢 صعودی" if r["direction"] == "LONG" else "🔴 نزولی"
            lines.append(
                f"▫️ <b>#{r['symbol']}</b> | {d_icon} | امتیاز: <code>{r['score']}/100</code> | قیمت: <code>{fmt_price(r['price'])}</code>"
            )
            cooldowns[r["symbol"]] = now_ts
        radar_msg = (
            f"👁 📡 <b>[رادار بازار • موقعیت‌های در حال شکل‌گیری • XT]</b>\n\n"
            + "\n".join(lines) +
            f"\n\n⚠️ <i>این لیست واچ‌لیست صرافی XT است؛ به محض رسیدن امتیاز به ۷۰+، سیگنال قطعی صادر می‌شود.</i>\n"
            f"#رادار_مارکت #صرافی_XT #تحت_نظر"
        )
        if send_telegram(radar_msg):
            save_json(COOLDOWN_FILE, cooldowns)

if __name__ == "__main__":
    main()
