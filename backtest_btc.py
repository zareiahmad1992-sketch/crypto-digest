#!/usr/bin/env python3
"""Bit-Mahdi backtest engine (research only, live system unchanged).

Correctness rules baked in:
  * closed candles only (Kraken's uncommitted last row is dropped)
  * outcomes measured only on candles closed AFTER the entry candle
  * every exit is priced: target/stop at their levels, unclear = 0R,
    invalidated & expired marked-to-market at the exit candle close
  * no look-ahead: higher-timeframe trends mapped by close time
  * history archive (data/history/*.csv) merged with the live 720-candle
    window so the sample keeps growing day by day

--base 30  : trio 30m/1h/4h   (live system logic)
--base 60  : trio 1h/4h/1d
--base 240 : trio 4h/1d/1w    (longest free history, ~100+ days)

Also prints a parameter-variant table (stop multiplier x target R) so
decisions are made on numbers, and a Wilson 95% CI for the win rate.
"""
import argparse
import bisect
import csv
import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import trend_alerts as t

TEHRAN = timezone(timedelta(hours=3, minutes=30))
HIST = Path("data/history")
TRIOS = {30: {"۳۰ دقیقه": 30, "۱ ساعت": 60, "۴ ساعت": 240},
         60: {"۱ ساعت": 60, "۴ ساعت": 240, "روزانه": 1440},
         240: {"۴ ساعت": 240, "روزانه": 1440, "هفتگی": 10080}}
HORIZON_H = {30: 24, 60: 48, 240: 240}
VARIANTS = [(1.5, 2.0), (2.0, 2.0), (2.0, 3.0), (2.5, 3.0)]


def load_history(interval):
    path = HIST / f"btc_{interval}.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [(int(r["ts"]), float(r["o"]), float(r["h"]),
                 float(r["l"]), float(r["c"])) for r in csv.DictReader(fh)]


def get_candles(interval):
    now = time.time()
    payload = t.SESSION.get(t.API, params={"pair": "XBTUSD", "interval": interval},
                            timeout=25).json()
    if payload.get("error"):
        raise ValueError(payload["error"])
    live = list(payload["result"].values())[0]
    live = [(int(r[0]), *(float(x) for x in r[1:5])) for r in live]
    merged = {r[0]: r for r in load_history(interval)}
    for r in live:
        merged.setdefault(r[0], r)
    rows = [r for r in sorted(merged.values()) if r[0] + interval * 60 <= now + 60]
    return rows


def trend_series(closes):
    f, s = t.ema_series(closes, 20), t.ema_series(closes, 50)
    return [("up" if a > b else "down" if a < b else "flat")
            if a is not None and b is not None else None for a, b in zip(f, s)]


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def run_engine(base, days, stop_mult, target_r, mode="trio"):
    trio = TRIOS[base]
    horizon = HORIZON_H[base] * 60 // base
    candles = {}
    for label, iv in trio.items():
        candles[label] = get_candles(iv)
        time.sleep(0.4)
    base_label = next(k for k, v in trio.items() if v == base)
    bc = candles[base_label]
    closes = [x[4] for x in bc]
    ct = [x[0] + base * 60 for x in bc]
    close_at = dict(zip(ct, closes))
    atr = t.atr_series(bc)
    trs = {label: trend_series([x[4] for x in candles[label]]) for label in trio}
    cts = {label: [x[0] + trio[label] * 60 for x in candles[label]] for label in trio}
    window_start = time.time() - days * 86400

    scenarios = []
    prev = {k: None for k in trio}
    prev["align"] = "mixed"
    for i in range(len(bc)):
        if ct[i] < window_start or atr[i] is None or i < 78:
            continue
        idx = {base_label: i}
        for label, iv in trio.items():
            if iv != base:
                idx[label] = bisect.bisect_right(cts[label], ct[i]) - 1
        trends = {label: trs[label][idx[label]] for label in trio}
        if any(v is None for v in trends.values()) or any(idx[l] < 0 for l in idx if trio[l] != base):
            continue
        high, low = bc[i][2], bc[i][3]
        for sc in scenarios:
            if sc["status"] != "open" or ct[i] <= sc["ts"]:
                continue
            if ct[i] - sc["ts"] > horizon * base * 60:
                sc["status"], sc["resolved_at"] = "expired", ct[i]
                continue
            if sc["direction"] == "up":
                hs, ht = low <= sc["stop"], high >= sc["target"]
            else:
                hs, ht = high >= sc["stop"], low <= sc["target"]
            if hs and ht:
                sc["status"], sc["resolved_at"] = "unclear", ct[i]
            elif hs:
                sc["status"], sc["resolved_at"] = "stop", ct[i]
            elif ht:
                sc["status"], sc["resolved_at"] = "target", ct[i]
        if mode == "cross":
            # research mode: trigger = EMA20/50 cross on the base chart itself,
            # higher timeframes only vote (they never block the trigger)
            base_tr = trends[base_label]
            if base_tr in ("up", "down") and base_tr != prev.get(base_label):
                for sc in scenarios:
                    if sc["status"] == "open" and sc["direction"] != base_tr:
                        sc["status"], sc["resolved_at"] = "invalidated", ct[i]
                distance = stop_mult * atr[i]
                sign = 1 if base_tr == "up" else -1
                votes = [(label, "agree" if trends[label] == base_tr else "against",
                          trends[label]) for label in trio if label != base_label]
                votes += t.confirmations(base_tr, bc[:i + 1])
                scenarios.append({"ts": ct[i], "direction": base_tr, "entry": closes[i],
                                  "stop": closes[i] - sign * distance,
                                  "target": closes[i] + sign * target_r * distance,
                                  "votes": votes, "status": "open", "resolved_at": None})
            prev = {**trends, "align": prev["align"]}
            continue
        align = t.alignment(trends)
        if align != prev["align"] and align in ("up", "down"):
            flipped = prev["align"] in ("up", "down")
            if flipped:
                for sc in scenarios:
                    if sc["status"] == "open" and sc["direction"] != align:
                        sc["status"], sc["resolved_at"] = "invalidated", ct[i]
            distance = stop_mult * atr[i]
            sign = 1 if align == "up" else -1
            votes = t.confirmations(align, bc[:i + 1]) if base != 240 else []
            scenarios.append({"ts": ct[i], "direction": align, "entry": closes[i],
                              "stop": closes[i] - sign * distance,
                              "target": closes[i] + sign * target_r * distance,
                              "votes": votes, "status": "open", "resolved_at": None})
        elif align != prev["align"] and prev["align"] in ("up", "down"):
            for sc in scenarios:
                if sc["status"] == "open":
                    sc["status"], sc["resolved_at"] = "invalidated", ct[i]
        prev = {**trends, "align": align}

    for sc in scenarios:
        risk = abs(sc["entry"] - sc["stop"]) or 1e-9
        sign = 1 if sc["direction"] == "up" else -1
        if sc["status"] == "target":
            sc["R"] = sign * (sc["target"] - sc["entry"]) / risk
        elif sc["status"] == "stop":
            sc["R"] = sign * (sc["stop"] - sc["entry"]) / risk
        elif sc["status"] == "unclear":
            sc["R"] = 0.0
        else:  # invalidated / expired: mark to market at exit close
            exit_price = close_at.get(sc["resolved_at"], sc["entry"])
            sc["R"] = sign * (exit_price - sc["entry"]) / risk
    return scenarios


def summarize(scenarios):
    stats = {k: sum(1 for s in scenarios if s["status"] == k)
             for k in ("target", "stop", "unclear", "expired", "invalidated")}
    decided = [s for s in scenarios if s["status"] in ("target", "stop")]
    wins = sum(1 for s in decided if s["status"] == "target")
    lo, hi = wilson(wins, len(decided))
    total_r = sum(s["R"] for s in scenarios)
    return {"n": len(scenarios), **stats, "wins": wins, "decided": len(decided),
            "winrate": (wins / len(decided)) if decided else 0.0,
            "ci": (lo, hi), "total_r": total_r,
            "avg_r": (total_r / len(scenarios)) if scenarios else 0.0}


def fa(ts):
    return datetime.fromtimestamp(ts, TEHRAN).strftime("%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=int, choices=(30, 60, 240), default=240)
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--mode", choices=("trio", "cross"), default="cross")
    args = ap.parse_args()
    base = args.base
    days = args.days or {30: 13, 60: 28, 240: 100}[base]

    scenarios = run_engine(base, days, 1.5, 2.0, args.mode)
    s = summarize(scenarios)
    variant_rows = []
    for sm, tr in VARIANTS:
        vs = summarize(run_engine(base, days, sm, tr, args.mode))
        variant_rows.append((sm, tr, vs))

    monthly = {}
    for sc in scenarios:
        key = datetime.fromtimestamp(sc["ts"], TEHRAN).strftime("%Y-%m")
        m = monthly.setdefault(key, {"n": 0, "r": 0.0})
        m["n"] += 1
        m["r"] += sc["R"]

    print(f"=== base {base}m, {days} days, mode={args.mode}, {len(scenarios)} scenarios ===")
    print("live statuses:", {k: s[k] for k in ("target", "stop", "unclear", "expired", "invalidated")})
    print(f"winrate (decided): {s['wins']}/{s['decided']} = {s['winrate']:.0%} "
          f"95% CI [{s['ci'][0]:.0%}, {s['ci'][1]:.0%}]  (breakeven 33% at 2R/1R)")
    print(f"total R (all exits priced): {s['total_r']:+.2f} | avg R per scenario: {s['avg_r']:+.2f}")
    print("variants (stop_mult, target_R) -> n, wins/decided, total R:")
    for sm, tr, vs in variant_rows:
        print(f"  {sm}xATR / {tr}R : n={vs['n']} win={vs['wins']}/{vs['decided']} "
              f"R={vs['total_r']:+.2f}")
    print("monthly R:", {k: f"{v['n']} scen, {v['r']:+.1f}R" for k, v in sorted(monthly.items())})
    for sc in scenarios:
        votes = " ".join(f"{tool}:{vote}" for tool, vote, _d in sc["votes"]) or "-"
        print(f"{fa(sc['ts'])} {sc['direction']:4} {sc['status']:11} R={sc['R']:+.2f} {votes}")

    # ---- HTML report ----
    bc = get_candles(base)
    time.sleep(0.4)
    ct = [x[0] + base * 60 for x in bc]
    closes = [x[4] for x in bc]
    w, h, pad = 940, 340, 30
    t0 = time.time() - days * 86400
    xs = [c for c in ct if c >= t0]
    ys = [c for c, cc in zip(ct, closes) if c >= t0]
    lo_p, hi_p = min(ys), max(ys)
    def X(ts): return pad + (ts - xs[0]) / (xs[-1] - xs[0]) * (w - 2 * pad)
    def Y(p): return h - pad - (p - lo_p) / (hi_p - lo_p) * (h - 2 * pad)
    path = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(xs, ys))
    marks = []
    for sc in scenarios:
        col = "#1a7f37" if sc["direction"] == "up" else "#c62828"
        marks.append(f'<circle cx="{X(sc["ts"]):.1f}" cy="{Y(sc["entry"]):.1f}" r="5" fill="{col}" stroke="#fff" stroke-width="1.5"><title>{fa(sc["ts"])} {sc["direction"]} → {sc["status"]} ({sc["R"]:+.2f}R)</title></circle>')
    ticks = ""
    d = datetime.fromtimestamp(xs[0], timezone.utc).replace(hour=0, minute=0, second=0)
    step = max(1, days // 8)
    while d.timestamp() <= xs[-1]:
        if d.timestamp() >= xs[0]:
            ticks += (f'<line x1="{X(d.timestamp()):.1f}" y1="{pad}" x2="{X(d.timestamp()):.1f}" y2="{h-pad}" stroke="#ddd"/>'
                      f'<text x="{X(d.timestamp()):.1f}" y="{h-8}" font-size="11" text-anchor="middle">{d:%m-%d}</text>')
        d += timedelta(days=step)
    rows_html = []
    for sc in scenarios:
        rows_html.append(
            f"<tr><td>{fa(sc['ts'])}</td><td>{'صعودی' if sc['direction']=='up' else 'نزولی'}</td>"
            f"<td>{sc['entry']:,.0f}</td><td>{sc['stop']:,.0f}</td><td>{sc['target']:,.0f}</td>"
            f"<td>{sc['status']}</td><td>{fa(sc['resolved_at'])}</td><td>{sc['R']:+.2f}</td></tr>")
    var_html = "".join(
        f"<tr><td>{sm}×ATR</td><td>{tr}R</td><td>{vs['n']}</td>"
        f"<td>{vs['wins']}/{vs['decided']}</td><td>{vs['winrate']:.0%}</td>"
        f"<td>{vs['total_r']:+.2f}</td></tr>" for sm, tr, vs in variant_rows)
    mon_html = "".join(f"<tr><td>{k}</td><td>{v['n']}</td><td>{v['r']:+.2f}</td></tr>"
                       for k, v in sorted(monthly.items()))
    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>بک‌تست مهندسی‌شده BTC پایه {base}m</title>
<style>body{{font-family:Segoe UI,Tahoma,sans-serif;margin:24px;background:#f6f7f9;color:#222}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:26px}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:center}}
.note{{background:#fff7e0;border:1px dashed #c9a227;padding:10px;border-radius:8px;font-size:13px;line-height:1.9}}
.ok{{background:#e8f5e9;border:1px solid #9ccc9c;padding:10px;border-radius:8px;font-size:14px;line-height:1.9}}
svg{{background:#fff;border-radius:10px;width:100%;height:auto}}
.stat{{display:inline-block;background:#fff;border:1px solid #ddd;border-radius:10px;padding:8px 14px;margin:4px;font-size:14px}}</style></head><body>
<h1>بک‌تست مهندسی‌شدهٔ Bit-Mahdi — پایهٔ {base} دقیقه‌ای — حالت {args.mode} — {days} روز — BTC/USD اسپات Kraken</h1>
<p class="note">قواعد درستی: فقط کندل بسته؛ نتیجه فقط روی کندل‌های بستهٔ بعد از ورود؛
همهٔ خروج‌ها قیمت‌گذاری می‌شوند (هدف/استاپ با سطح خود، باطل/منقضی با قیمت بستهٔ لحظهٔ خروج)؛
تاریخچهٔ آرشیوشده با پنجرهٔ زنده ادغام می‌شود. سیستم زنده بدون تغییر مانده است.</p>
<div class="ok">نرخ برد تصمیم‌گرفته‌شده: {s['wins']}/{s['decided']} = {s['winrate']:.0%}
 | بازهٔ اطمینان ۹۵٪: [{s['ci'][0]:.0%} تا {s['ci'][1]:.0%}] | سربه‌سر با هدف ۲R و استاپ ۱R: ۳۳٪
<br>مجموع R همهٔ سناریوها: {s['total_r']:+.2f} | میانگین R به ازای هر سناریو: {s['avg_r']:+.2f}</div>
<div>
<span class="stat">سناریوها: {s['n']}</span>
<span class="stat">✅ {s['target']} | ❌ {s['stop']} | ⚪ {s['unclear']} | 🕰 {s['expired']} | 🚫 {s['invalidated']}</span>
</div>
<h2>نمودار</h2>
<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">
{ticks}<polyline points="{path}" fill="none" stroke="#37474f" stroke-width="1.3"/>{''.join(marks)}</svg>
<h2>جدول واریانت‌های پارامتر (پژوهشی — سیستم زنده عوض نشده)</h2>
<table><tr><th>استاپ</th><th>هدف</th><th>سناریو</th><th>برد/تصمیم</th><th>نرخ برد</th><th>مجموع R</th></tr>{var_html}</table>
<h2>تفکیک ماهانه</h2>
<table><tr><th>ماه</th><th>سناریو</th><th>مجموع R</th></tr>{mon_html}</table>
<h2>جدول سناریوها (تهران)</h2>
<table><tr><th>ورود</th><th>جهت</th><th>ورود$</th><th>استاپ$</th><th>هدف$</th><th>خروج</th><th>زمان خروج</th><th>R</th></tr>
{''.join(rows_html)}</table>
</body></html>"""
    out = f"samples/backtest_engine_{base}m_{args.mode}.html"
    Path(out).write_text(html, encoding="utf-8")
    print("written:", out)


if __name__ == "__main__":
    main()
