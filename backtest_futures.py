#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_futures.py — بک‌تست استراتژی نهادی چندتاییدی (Multi-Confluence)
شبیه‌سازی کامل کارمزد، اسلیپیج و فیلترهای ضد رِنج
"""
import argparse
import time
from datetime import datetime, timedelta, timezone
import requests
import trend_alerts as t

BASE_URL = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "TONUSDT")
TIMEFRAMES = ("1h", "4h") # حذف تایم‌های نوسانی و تمرکز بر سود مطمئن

FEE_RATE = 0.0005       # 0.05% کارمزد هر طرف
SLIPPAGE_RATE = 0.0002  # 0.02% اسلیپیج قیمت
SESSION = requests.Session()

def utc_date(val):
    return datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=timezone.utc)

def fetch_klines(symbol, interval, start, end):
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    cursor = start_ms
    rows = []
    while cursor < end_ms:
        r = SESSION.get(f"{BASE_URL}/fapi/v1/klines", params={
            "symbol": symbol, "interval": interval,
            "startTime": cursor, "endTime": end_ms - 1, "limit": 1500
        }, timeout=25).json()
        if not r or not isinstance(r, list): break
        for row in r:
            ts, close_ms = int(row[0]), int(row[6])
            if ts >= start_ms and close_ms < end_ms:
                rows.append((ts // 1000, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
        next_cursor = int(r[-1][0]) + 1
        if next_cursor <= cursor: break
        cursor = next_cursor
        time.sleep(0.1)
    unique = {row[0]: row for row in rows}
    return [unique[k] for k in sorted(unique)]

def run_confluence_backtest(rows, start_ts, end_ts):
    if len(rows) < 60: return []
    closes = [r[4] for r in rows]
    vols = [r[5] for r in rows]
    
    ema20 = t.ema_series(closes, 20)
    ema50 = t.ema_series(closes, 50)
    rsi = t.rsi_series(closes, 14)
    atr = t.atr_series(rows, 14)
    
    trades = []
    pos = None

    for i in range(50, len(rows)):
        ts, op, hi, lo, cl, vo = rows[i]
        if ts < start_ts or ts >= end_ts: continue

        # میانگین حجم ۲۰ کندل قبل
        avg_v = sum(vols[i-20:i]) / 20 if i >= 20 else 1.0
        rvol = vo / avg_v if avg_v > 0 else 1.0

        # سیگنال ورود با تاییدیه‌های چندگانه
        if pos is None:
            long_cond = (ema20[i-1] > ema50[i-1]) and (cl > ema50[i-1]) and (45 <= rsi[i-1] <= 65) and (rvol >= 1.2)
            short_cond = (ema20[i-1] < ema50[i-1]) and (cl < ema50[i-1]) and (35 <= rsi[i-1] <= 55) and (rvol >= 1.2)

            if long_cond or short_cond:
                direction = 1 if long_cond else -1
                entry = op * (1 + SLIPPAGE_RATE if direction == 1 else 1 - SLIPPAGE_RATE)
                stop_dist = 1.5 * (atr[i-1] or (entry * 0.02))
                stop = entry - (direction * stop_dist)
                tp1 = entry + (direction * 1.5 * stop_dist)
                tp2 = entry + (direction * 2.5 * stop_dist)

                pos = {"dir": direction, "entry": entry, "sl": stop, "tp1": tp1, "tp2": tp2, "status": "OPEN"}

        # مدیریت پوزیشن باز
        elif pos is not None:
            d, entry, sl, tp1, tp2 = pos["dir"], pos["entry"], pos["sl"], pos["tp1"], pos["tp2"]
            
            # برخورد با استاپ لاس
            hit_sl = (lo <= sl) if d == 1 else (hi >= sl)
            # برخورد با تارگت اول (انتقال به ریسک‌فری)
            hit_tp1 = (hi >= tp1) if d == 1 else (lo <= tp1)
            # برخورد با تارگت نهایی
            hit_tp2 = (hi >= tp2) if d == 1 else (lo <= tp2)

            if pos["status"] == "OPEN":
                if hit_tp1:
                    pos["status"] = "RISK_FREE"
                    pos["sl"] = entry # استاپ به نقطه ورود می‌آید
                elif hit_sl:
                    gross = d * (sl - entry) / entry
                    trades.append({"ret": gross - (FEE_RATE * 2), "win": False})
                    pos = None

            elif pos["status"] == "RISK_FREE":
                if hit_tp2:
                    gross = d * (tp2 - entry) / entry
                    trades.append({"ret": gross - (FEE_RATE * 2), "win": True})
                    pos = None
                elif hit_sl: # خروج بدون ضرر
                    trades.append({"ret": 0.0 - (FEE_RATE * 2), "win": True})
                    pos = None

    return trades

def print_metrics(label, trades):
    if not trades:
        print(f"  {label}: بدون معامله تاییدشده (فیلتر بازار نامناسب)")
        return
    wins = sum(1 for t in trades if t["ret"] > 0)
    tot = sum(t["ret"] for t in trades)
    print(f"  {label}: معامله={len(trades)} | برد={wins/len(trades)*100:.1f}% | بازده خالص کل={tot*100:+.2f}%")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--split", default="2024-08-01")
    parser.add_argument("--end", default="2024-12-01")
    args = parser.parse_args()

    s, sp, e = utc_date(args.start), utc_date(args.split), utc_date(args.end)
    warmup = s - timedelta(days=40)

    print(f"🧪 اجرای بک‌تست هوشمند چندتاییدی (Multi-Confluence + Risk-Free Engine)")
    print(f"قوانین: تاییدیه حجم (RVol) + فیلتر RSI + انتقال استاپ به نقطه ورود در TP1\n")

    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            print(f"📊 {sym} | تایم‌فریم: {tf}")
            rows = fetch_klines(sym, tf, warmup, e)
            train = run_confluence_backtest(rows, int(s.timestamp()), int(sp.timestamp()))
            test = run_confluence_backtest(rows, int(sp.timestamp()), int(e.timestamp()))
            print_metrics("دوره آموزش (Train)", train)
            print_metrics("دوره تست خارج نمونه (Test)", test)
            print("-" * 50)

if __name__ == "__main__":
    main()
