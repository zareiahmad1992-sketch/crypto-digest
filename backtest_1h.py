#!/usr/bin/env python3
"""1H-chart backtest: trigger = EMA20/50 cross on the 1h chart (closed candles).

Confirmation votes at the trigger candle:
  4h trend, daily trend, RSI14(1h), Ichimoku cloud(1h)
Scenario: entry = 1h close, stop = 1.5xATR14(1h), target = 2R.
Live-style resolution on each closed 1h candle; an opposite 1h cross
invalidates the open scenario; horizon 48h otherwise.
Kraken public OHLC caps at the latest 720 candles (~29 days on 1h).
Research only — writes samples/backtest_btc_1h_cross.html
"""
import bisect
import time
from datetime import datetime, timezone, timedelta

import trend_alerts as t

TEHRAN = timezone(timedelta(hours=3, minutes=30))
HORIZON = 48  # 1h candles


def fetch_recent(interval):
    payload = t.SESSION.get(t.API, params={"pair": "XBTUSD", "interval": interval},
                            timeout=25).json()
    if payload.get("error"):
        raise ValueError(payload["error"])
    rows = list(payload["result"].values())[0]
    rows = [(int(r[0]), *(float(x) for x in r[1:5])) for r in rows]
    return [r for r in rows if r[0] + interval * 60 <= time.time() + 60]


def trend_series(closes):
    f, s = t.ema_series(closes, 20), t.ema_series(closes, 50)
    return [("up" if a > b else "down" if a < b else "flat")
            if a is not None and b is not None else None for a, b in zip(f, s)]


def fa(ts):
    return datetime.fromtimestamp(ts, TEHRAN).strftime("%m-%d %H:%M")


def main():
    c1 = fetch_recent(60); time.sleep(1)
    c4 = fetch_recent(240); time.sleep(1)
    cD = fetch_recent(1440)
    ct1 = [x[0] + 3600 for x in c1]
    ct4 = [x[0] + 86400 // 6 for x in c4]
    ctD = [x[0] + 86400 for x in cD]
    tr1 = trend_series([x[4] for x in c1])
    tr4 = trend_series([x[4] for x in c4])
    trD = trend_series([x[4] for x in cD])
    atr1 = t.atr_series(c1)

    scenarios = []
    for i in range(1, len(c1)):
        if tr1[i] is None or tr1[i - 1] is None or tr1[i] == tr1[i - 1] or atr1[i] is None:
            continue
        if tr1[i] not in ("up", "down"):
            continue
        d = tr1[i]
        j4 = bisect.bisect_right(ct4, ct1[i]) - 1
        jD = bisect.bisect_right(ctD, ct1[i]) - 1
        if j4 < 0 or jD < 0 or tr4[j4] is None or trD[jD] is None:
            continue
        votes = [("۴ساعت", "agree" if tr4[j4] == d else "against", tr4[j4]),
                 ("روزانه", "agree" if trD[jD] == d else "against", trD[jD])]
        votes += t.confirmations(d, c1[:i + 1])
        levels = t.scenario(d, c1[i][4], atr1[i])
        scenarios.append({"ts": ct1[i], "direction": d, "entry": c1[i][4],
                          "stop": levels[1], "target": levels[2],
                          "votes": votes, "status": "open", "resolved_at": None})

    for i in range(len(c1)):
        high, low = c1[i][2], c1[i][3]
        for sc in scenarios:
            if sc["status"] != "open" or ct1[i] <= sc["ts"]:
                continue
            if tr1[i] == ("down" if sc["direction"] == "up" else "up"):
                sc["status"], sc["resolved_at"] = "invalidated", ct1[i]
                continue
            if ct1[i] - sc["ts"] > HORIZON * 3600:
                sc["status"], sc["resolved_at"] = "expired", ct1[i]
                continue
            if sc["direction"] == "up":
                hs, ht = low <= sc["stop"], high >= sc["target"]
            else:
                hs, ht = high >= sc["stop"], low <= sc["target"]
            if hs and ht:
                sc["status"], sc["resolved_at"] = "unclear", ct1[i]
            elif hs:
                sc["status"], sc["resolved_at"] = "stop", ct1[i]
            elif ht:
                sc["status"], sc["resolved_at"] = "target", ct1[i]

    for sc in scenarios:
        if sc["status"] != "open":
            sc["held"], sc["held_at"] = sc["status"], sc["resolved_at"]
            continue
        start = bisect.bisect_right(ct1, sc["ts"])
        held, at = "expired", ct1[-1]
        for j in range(start, min(start + HORIZON, len(c1))):
            high, low = c1[j][2], c1[j][3]
            if sc["direction"] == "up":
                hs, ht = low <= sc["stop"], high >= sc["target"]
            else:
                hs, ht = high >= sc["stop"], low <= sc["target"]
            if hs and ht:
                held, at = "unclear", ct1[j]
                break
            if hs:
                held, at = "stop", ct1[j]
                break
            if ht:
                held, at = "target", ct1[j]
                break
        sc["held"], sc["held_at"] = held, at

    def gate(sc):
        return all(v[1] == "agree" for v in sc["votes"][:2])  # 4h + daily

    stats = {k: sum(1 for s in scenarios if s["status"] == k)
             for k in ("target", "stop", "unclear", "expired", "invalidated")}
    gated = [s for s in scenarios if gate(s)]
    ungated = [s for s in scenarios if not gate(s)]

    def wr(xs, key="held"):
        done = [s for s in xs if s[key] in ("target", "stop")]
        return sum(1 for s in done if s[key] == "target"), len(done)

    rows = []
    for sc in scenarios:
        v = {tool: (vote, det) for tool, vote, det in sc["votes"]}
        agree = sum(1 for _t, vote, _d in sc["votes"] if vote == "agree")
        lab = {"up": "صعودی", "down": "نزولی", "flat": "خنثی"}
        rows.append(
            f"<tr><td>{fa(sc['ts'])}</td><td>{'صعودی' if sc['direction']=='up' else 'نزولی'}</td>"
            f"<td>{lab.get(v['۴ساعت'][1], v['۴ساعت'][1])}</td><td>{lab.get(v['روزانه'][1], v['روزانه'][1])}</td>"
            f"<td>{v['RSI۱۴'][1]} {t.VOTE_LABELS[v['RSI۱۴'][0]]}</td>"
            f"<td>{t.VOTE_LABELS[v['ایچیموکو'][0]]}</td>"
            f"<td>{agree}/4</td><td>{sc['entry']:,.0f}</td><td>{sc['stop']:,.0f}</td><td>{sc['target']:,.0f}</td>"
            f"<td>{sc['status']} @ {fa(sc['resolved_at'])}</td>"
            f"<td>{sc['held']} @ {fa(sc['held_at'])}</td></tr>")

    xs, ys = ct1, [x[4] for x in c1]
    w, h, pad = 940, 340, 30
    t0, t1_, lo, hi = xs[0], xs[-1], min(ys), max(ys)
    def X(ts): return pad + (ts - t0) / (t1_ - t0) * (w - 2 * pad)
    def Y(p): return h - pad - (p - lo) / (hi - lo) * (h - 2 * pad)
    path = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(xs, ys))
    marks = []
    for sc in scenarios:
        col = "#1a7f37" if sc["direction"] == "up" else "#c62828"
        marks.append(f'<circle cx="{X(sc["ts"]):.1f}" cy="{Y(sc["entry"]):.1f}" r="5" fill="{col}" stroke="#fff" stroke-width="1.5"><title>{fa(sc["ts"])} {sc["direction"]} → {sc["held"]}</title></circle>')
        if sc["held"] in ("target", "stop"):
            mc = "#1a7f37" if sc["held"] == "target" else "#c62828"
            marks.append(f'<rect x="{X(sc["held_at"])-3:.1f}" y="{Y(sc["entry"])-3:.1f}" width="6" height="6" fill="none" stroke="{mc}" stroke-width="2"/>')
    ticks = ""
    d = datetime.fromtimestamp(t0, timezone.utc).replace(hour=0, minute=0, second=0)
    while d.timestamp() <= t1_:
        ticks += (f'<line x1="{X(d.timestamp()):.1f}" y1="{pad}" x2="{X(d.timestamp()):.1f}" y2="{h-pad}" stroke="#ddd"/>'
                  f'<text x="{X(d.timestamp()):.1f}" y="{h-8}" font-size="11" text-anchor="middle">{d:%m-%d}</text>')
        d += timedelta(days=4)

    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>بک‌تست چارت ۱ساعته BTC</title>
<style>body{{font-family:Segoe UI,Tahoma,sans-serif;margin:24px;background:#f6f7f9;color:#222}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:center}}
.note{{background:#fff7e0;border:1px dashed #c9a227;padding:10px;border-radius:8px;font-size:13px;line-height:1.9}}
svg{{background:#fff;border-radius:10px;width:100%;height:auto}}
.stat{{display:inline-block;background:#fff;border:1px solid #ddd;border-radius:10px;padding:8px 14px;margin:4px;font-size:14px}}</style></head><body>
<h1>بک‌تست چارت ۱ساعته BTC/USD — تریگر: کراس EMA۲۰/۵۰ در ۱ساعت — ~۲۹ روز گذشته (Kraken)</h1>
<p class="note">تریگر = تغییر روند روی خود چارت ۱ساعته؛ تأییدیه‌ها = روند ۴ساعت، روند روزانه، RSI۱۴ و ایچیموکو روی ۱ساعت.
«گیت بالاتر» یعنی هر دو تایم‌فریم بالاتر هم‌جهت با تریگر. خروج زودهنگام هنگام کراس مخالفِ ۱ساعته؛ افق ۴۸ ساعت.
پژوهشی است و تضمین نیست؛ API رایگان Kraken فقط ۷۲۰ کندل آخرِ هر تایم‌فریم می‌دهد.</p>
<div>
<span class="stat">تریگرها: {len(scenarios)}</span>
<span class="stat">زنده — ✅ {stats['target']} | ❌ {stats['stop']} | 🚫 {stats['invalidated']} | 🕰/⚪ {stats['expired']+stats['unclear']}</span>
<span class="stat">با گیت بالاتر (نگه‌داشته): {wr(gated)[0]}/{wr(gated)[1]}</span>
<span class="stat">بدون گیت (نگه‌داشته): {wr(ungated)[0]}/{wr(ungated)[1]}</span>
</div>
<h2>نمودار ۱ساعته و نقطه‌ها</h2>
<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">
{ticks}<polyline points="{path}" fill="none" stroke="#37474f" stroke-width="1.2"/>
{''.join(marks)}
</svg>
<h2>جدول تریگرها (زمان تهران)</h2>
<table><tr><th>زمان</th><th>جهت</th><th>۴ساعت</th><th>روزانه</th><th>RSI۱۴</th><th>ایچیموکو</th><th>رأی</th><th>ورود$</th><th>استاپ$</th><th>هدف$</th><th>نتیجه زنده</th><th>نگه‌داشته</th></tr>
{''.join(rows)}</table>
</body></html>"""
    open("samples/backtest_btc_1h_cross.html", "w", encoding="utf-8").write(html)
    print("triggers:", len(scenarios), "live:", stats)
    print("gated held win:", wr(gated), "| ungated:", wr(ungated))
    for sc in scenarios:
        print(fa(sc["ts"]), sc["direction"],
              "votes:", [(tool, vote) for tool, vote, _d in sc["votes"]],
              "| live:", sc["status"], "| held:", sc["held"])


if __name__ == "__main__":
    main()
