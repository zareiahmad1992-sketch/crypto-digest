#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trend_alerts.py — موتور فوق‌پیشرفته تحلیل تکنیکال و سنتیمنت بازار
شامل: EMA 20/50/200, Ichimoku, MACD, RSI, ATR, RVol, Market Structure و فاندینگ ریت
"""
import time
import requests

BASE_URL = "https://fapi.binance.com"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "InstitutionalCryptoScanner/3.0"})

# لیست ارزهای با نقدشوندگی و عمق مارکت بالا
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "NEARUSDT", "TONUSDT", "SUIUSDT",
    "LINKUSDT", "APTUSDT", "DOGEUSDT"
]

# ═══════════════ دریافت داده‌ها ═══════════════
def fetch_klines(symbol: str, interval: str = "4h", limit: int = 120):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = SESSION.get(url, params=params, timeout=12)
        r.raise_for_status()
        rows = []
        for row in r.json():
            # (timestamp, open, high, low, close, volume)
            rows.append((
                int(row[0]) // 1000,
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5])
            ))
        return rows
    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return []

def fetch_derivatives_data(symbol: str):
    """دریافت فاندینگ ریت برای جلوگیری از دام‌های لیکوییدیشن"""
    try:
        url = f"{BASE_URL}/fapi/v1/premiumIndex"
        r = SESSION.get(url, params={"symbol": symbol}, timeout=8)
        data = r.json()
        funding = float(data.get("lastFundingRate", 0.0)) * 100
        return {"funding_rate_pct": funding}
    except Exception:
        return {"funding_rate_pct": 0.0}

# ═══════════════ محاسبات اندیکاتورها ═══════════════
def ema_series(closes: list, period: int):
    if len(closes) < period:
        return [None] * len(closes)
    ema = [None] * len(closes)
    ema[period - 1] = sum(closes[:period]) / period
    multiplier = 2 / (period + 1)
    for i in range(period, len(closes)):
        ema[i] = (closes[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema

def rsi_series(closes: list, period: int = 14):
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
    rsi = [None] * len(closes)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return rsi

def macd_series(closes: list, fast=12, slow=26, signal=9):
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        macd_line.append(f - s if (f is not None and s is not None) else None)
    
    valid_macd = [x for x in macd_line if x is not None]
    if len(valid_macd) < signal:
        return None, None, None
    
    signal_line_valid = ema_series(valid_macd, signal)
    signal_line = [None] * (len(macd_line) - len(valid_macd)) + signal_line_valid
    
    hist = []
    for m, s in zip(macd_line, signal_line):
        hist.append(m - s if (m is not None and s is not None) else None)
    return macd_line, signal_line, hist

def atr_series(rows: list, period: int = 14):
    if len(rows) < period + 1:
        return [None] * len(rows)
    tr_list = [rows[0][2] - rows[0][3]]
    for i in range(1, len(rows)):
        h, l, pc = rows[i][2], rows[i][3], rows[i - 1][4]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [None] * len(rows)
    atr[period] = sum(tr_list[1:period + 1]) / period
    for i in range(period + 1, len(rows)):
        atr[i] = (atr[i - 1] * (period - 1) + tr_list[i]) / period
    return atr

def ichimoku_cloud(rows: list):
    """محاسبه کامل ابر ایچیموکو، تنکان‌سن و کیجون‌سن"""
    if len(rows) < 52:
        return None
    def donchian(p, idx):
        highs = [rows[j][2] for j in range(idx - p + 1, idx + 1)]
        lows = [rows[j][3] for j in range(idx - p + 1, idx + 1)]
        return (max(highs) + min(lows)) / 2

    last = len(rows) - 1
    tenkan = donchian(9, last)
    kijun = donchian(26, last)
    # Span A & B مربوط به موقعیت فعلی کندل
    span_a = donchian(9, last - 26) + donchian(26, last - 26) / 2
    span_b = donchian(52, last - 26)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "cloud_top": max(span_a, span_b),
        "cloud_bottom": min(span_a, span_b),
        "bullish_cloud": span_a > span_b
    }

def detect_market_structure(rows: list):
    """تشخیص شکست ساختار (BOS) و حمایت/مقاومت کلیدی"""
    if len(rows) < 30:
        return "UNKNOWN", 0.0, 0.0
    recent = rows[-20:]
    highs = [r[2] for r in recent[:-2]]
    lows = [r[3] for r in recent[:-2]]
    swing_high = max(highs)
    swing_low = min(lows)
    current_close = rows[-1][4]
    
    if current_close > swing_high:
        return "BULLISH_BOS", swing_high, swing_low
    elif current_close < swing_low:
        return "BEARISH_BOS", swing_high, swing_low
    return "RANGE", swing_high, swing_low

# ═══════════════ موتور امتیازدهی چندتاییدی ═══════════════
def inspect_market_deep(symbol: str):
    rows_4h = fetch_klines(symbol, "4h", limit=120)
    rows_1h = fetch_klines(symbol, "1h", limit=100)
    if len(rows_4h) < 60 or len(rows_1h) < 60:
        return None

    closes_4h = [r[4] for r in rows_4h]
    closes_1h = [r[4] for r in rows_1h]
    vols_1h = [r[5] for r in rows_1h]
    current_price = closes_1h[-1]

    # محاسبه اندیکاتورها
    ema200_4h = ema_series(closes_4h, 200)[-1] or ema_series(closes_4h, 50)[-1]
    ema50_4h = ema_series(closes_4h, 50)[-1]
    ichi_4h = ichimoku_cloud(rows_4h)
    
    ema20_1h = ema_series(closes_1h, 20)[-1]
    ema50_1h = ema_series(closes_1h, 50)[-1]
    rsi_1h = rsi_series(closes_1h, 14)[-1]
    _, _, hist_1h = macd_series(closes_1h)
    macd_hist = hist_1h[-1] if hist_1h else 0
    atr_1h = atr_series(rows_1h, 14)[-1]
    structure, s_high, s_low = detect_market_structure(rows_1h)
    derivs = fetch_derivatives_data(symbol)

    # حجم نسبی (RVol)
    avg_vol = sum(vols_1h[-21:-1]) / 20 if len(vols_1h) >= 21 else 1.0
    rvol = vols_1h[-1] / avg_vol if avg_vol > 0 else 1.0

    if not all([ema50_4h, ichi_4h, ema20_1h, ema50_1h, rsi_1h, atr_1h]):
        return None

    # سیستم امتیازدهی تاییدیه (Confluence Scoring)
    long_points = 0
    short_points = 0
    reasons = []

    # 1. فیلتر ترند ماکرو 4H
    if current_price > ichi_4h["cloud_top"] and current_price > ema50_4h:
        long_points += 25
        reasons.append("قیمت بالای ابر کومو و EMA50 در ۴ساعته")
    elif current_price < ichi_4h["cloud_bottom"] and current_price < ema50_4h:
        short_points += 25
        reasons.append("قیمت زیر ابر کومو و EMA50 در ۴ساعته")

    # 2. فیلتر میانگین متحرک و مکدی 1H
    if ema20_1h > ema50_1h and macd_hist > 0:
        long_points += 20
        reasons.append("تقاطع صعودی EMA 20/50 و MACD مثبت")
    elif ema20_1h < ema50_1h and macd_hist < 0:
        short_points += 20
        reasons.append("تقاطع نزولی EMA 20/50 و MACD منفی")

    # 3. فیلتر مومنتوم RSI (جلوگیری از ورود در سقف/کف هیجانی)
    if 45 <= rsi_1h <= 65:
        long_points += 15
    elif 35 <= rsi_1h <= 55:
        short_points += 15

    # 4. حجم پول هوشمند (RVol)
    if rvol >= 1.25:
        long_points += 15
        short_points += 15
        reasons.append(f"تایید حجم غیرعادی ({rvol:.1f}x)")

    # 5. شکست ساختار (Market Structure)
    if structure == "BULLISH_BOS":
        long_points += 15
        reasons.append("شکست سقف ماقبل (Bullish BOS)")
    elif structure == "BEARISH_BOS":
        short_points += 15
        reasons.append("شکست کف ماقبل (Bearish BOS)")

    # 6. فاندینگ ریت (بررسی دام شورت/لانگ اسکوئیز)
    fr = derivs["funding_rate_pct"]
    if fr < -0.01:  # شورت‌های سنگین در بازار -> احتمال پامپ
        long_points += 10
    elif fr > 0.03: # لانگ‌های سنگین در بازار -> احتمال دامپ
        short_points += 10

    # تصمیم‌گیری نهایی (فقط امتیاز بالای 75 صادر می‌شود)
    signal = "NEUTRAL"
    score = 0
    if long_points >= 75 and long_points > short_points:
        signal = "BUY/LONG"
        score = long_points
    elif short_points >= 75 and short_points > long_points:
        signal = "SELL/SHORT"
        score = short_points
    else:
        return None

    # سطوح خروج با R:R حداقل 1:2
    stop_dist = 1.5 * atr_1h
    if signal == "BUY/LONG":
        entry = current_price
        stop = max(entry - stop_dist, s_low)
        tp1 = entry + 1.5 * (entry - stop)
        tp2 = entry + 2.5 * (entry - stop)
    else:
        entry = current_price
        stop = min(entry + stop_dist, s_high)
        tp1 = entry - 1.5 * (stop - entry)
        tp2 = entry - 2.5 * (stop - entry)

    return {
        "symbol": symbol.replace("USDT", ""),
        "pair": symbol,
        "signal": signal,
        "score": score,
        "price": entry,
        "stop_loss": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rsi": round(rsi_1h, 1),
        "rvol": round(rvol, 2),
        "funding": fr,
        "reasons": reasons
    }

def send_telegram(token: str, chat_id: str, message: str):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=12)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False
