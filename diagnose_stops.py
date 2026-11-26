#!/usr/bin/env python3
"""Stop-loss forensics: why does the system get stopped so often?

For every stopped scenario we measure:
  * wick-only stop (close stayed beyond? no: close did NOT pass the stop)
    vs close-through stop (real reversal)
  * whether the target would have been hit LATER in the horizon
    (direction right, stop too tight / entry too late)
  * hours from entry to stop
  * entry overextension |close-EMA20|/ATR  (chasing entries?)
  * ATR percentile at entry (high-vol regime?)

Then reruns the trigger loop with candidate fixes (filters / wider stops /
next-candle-open entry) so we can see which hypothesis actually removes
the losing stops — all on past data, so winners are HYPOTHESES that must
later be validated out-of-sample on the growing history archive.
"""
import bisect
import time
from datetime import datetime, timezone, timedelta

import trend_alerts as t
from backtest_btc import get_candles, trend_series, wilson, TRIOS, HORIZON_H

TEHRAN = timezone(timedelta(hours=3, minutes=30))
WINDOWS = {30: 13, 60: 28, 240: 100}


def run(base, stop_mult=1.5, target_r=2.0, max_overext=None,
        max_atr_pct=None, need_higher_tf=False, next_open=False):
    trio = TRIOS[base]
    horizon = HORIZON_H[base] * 60 // base
    candles = {label: get_candles(iv) for label, iv in trio.items()}
    time.sleep(0.3)
    base_label = next(k for k, v in trio.items() if v == base)
    bc = candles[base_label]
    closes = [x[4] for x in bc]
    ct = [x[0] + base * 60 for x in bc]
    atr = t.atr_series(bc)
    ema20 = t.ema_series(closes, 20)
    trs = {label: trend_series([x[4] for x in candles[label]]) for label in trio}
    cts = {label: [x[0] + trio[label] * 60 for x in candles[label]] for label in trio}
    window_start = time.time() - WINDOWS[base] * 86400
    scenarios = []
    prev_tr = {k: None for k in trio}
    for i in range(1, len(bc)):
        if ct[i] < window_start or atr[i] is None or i < 78:
            continue
        idx = {base_label: i}
        for label, iv in trio.items():
            if iv != base:
                idx[label] = bisect.bisect_right(cts[label], ct[i]) - 1
        trends = {label: trs[label][idx[label]] for label in trio}
        if any(v is None for v in trends.values()) or any(idx[l] < 0 for l in idx if trio[l] != base):
            continue
        d = trends[base_label]
        if d in ("up", "down") and d != prev_tr[base_label]:
            overext = abs(closes[i] - ema20[i]) / atr[i] if atr[i] else 0
            past = [a for a in atr[78:i + 1] if a]
            atr_pct = 100.0 * sum(1 for a in past if a <= atr[i]) / len(past)
            higher_ok = any(trends[l] == d for l in trio if l != base_label)
            if (max_overext is None or overext <= max_overext) and \
               (max_atr_pct is None or atr_pct <= max_atr_pct) and \
               (not need_higher_tf or higher_ok):
                for sc in scenarios:
                    if sc["status"] == "open" and sc["direction"] != d:
                        sc["status"], sc["resolved_at"] = "invalidated", ct[i]
                entry_i = i + 1 if next_open else i
                if entry_i < len(bc):
                    entry = bc[entry_i][1] if next_open else closes[i]
                    distance = stop_mult * atr[i]
                    sign = 1 if d == "up" else -1
                    scenarios.append({
                        "ts": ct[i], "direction": d, "entry": entry,
                        "stop": entry - sign * distance,
                        "target": entry + sign * target_r * distance,
                        "status": "open", "resolved_at": None,
                        "overext": overext, "atr_pct": atr_pct,
                        "entry_i": entry_i, "higher_ok": higher_ok})
        prev_tr = {**trends}
        # resolve open scenarios on this closed candle (after triggers)
        high, low, close = bc[i][2], bc[i][3], bc[i][4]
        for sc in scenarios:
            if sc["status"] != "open" or i < sc["entry_i"] or ct[i] <= sc["ts"]:
                continue
            if ct[i] - sc["ts"] > horizon * base * 60:
                sc["status"], sc["resolved_at"] = "expired", ct[i]
                continue
            if sc["direction"] == "up":
                hs, ht = low <= sc["stop"], high >= sc["target"]
                close_through = close <= sc["stop"]
            else:
                hs, ht = high >= sc["stop"], low <= sc["target"]
                close_through = close >= sc["stop"]
            if hs and ht:
                sc["status"], sc["resolved_at"] = "unclear", ct[i]
            elif hs:
                sc["status"], sc["resolved_at"] = "stop", ct[i]
                sc["close_through"] = close_through
                sc["hours_to_stop"] = (ct[i] - sc["ts"]) / 3600
                later = False
                for j in range(i + 1, min(i + 1 + horizon, len(bc))):
                    hj, lj = bc[j][2], bc[j][3]
                    hit = hj >= sc["target"] if sc["direction"] == "up" else lj <= sc["target"]
                    if hit:
                        later = True
                        break
                sc["target_after_stop"] = later
            elif ht:
                sc["status"], sc["resolved_at"] = "target", ct[i]
                sc["hours_to_target"] = (ct[i] - sc["ts"]) / 3600
    for sc in scenarios:
        if sc["status"] == "open":
            sc["status"], sc["resolved_at"] = "expired", ct[-1]
    for sc in scenarios:
        risk = abs(sc["entry"] - sc["stop"]) or 1e-9
        sign = 1 if sc["direction"] == "up" else -1
        if sc["status"] == "target":
            sc["R"] = sign * (sc["target"] - sc["entry"]) / risk
        elif sc["status"] == "stop":
            sc["R"] = -1.0
        elif sc["status"] == "unclear":
            sc["R"] = 0.0
        else:
            exit_i = bisect.bisect_left(ct, sc["resolved_at"])
            exit_price = closes[exit_i] if exit_i < len(closes) else sc["entry"]
            sc["R"] = sign * (exit_price - sc["entry"]) / risk
    return scenarios


def summarize(scenarios):
    stops = [s for s in scenarios if s["status"] == "stop"]
    wick = [s for s in stops if not s.get("close_through")]
    then_target = [s for s in stops if s.get("target_after_stop")]
    decided = [s for s in scenarios if s["status"] in ("target", "stop")]
    wins = sum(1 for s in decided if s["status"] == "target")
    return {"n": len(scenarios), "stops": len(stops), "wick_stops": len(wick),
            "stopped_then_target": len(then_target),
            "wins": wins, "decided": len(decided),
            "total_r": sum(s["R"] for s in scenarios),
            "avg_h_to_stop": (sum(s.get("hours_to_stop", 0) for s in stops) / len(stops)) if stops else 0}


def main():
    print("=== STOP FORENSICS (cross mode, default 1.5xATR / 2R) ===")
    for base in (30, 60, 240):
        scs = run(base)
        s = summarize(scs)
        stops = [x for x in scs if x["status"] == "stop"]
        wins = [x for x in scs if x["status"] == "target"]
        ov_stop = (sum(x["overext"] for x in stops) / len(stops)) if stops else 0
        ov_win = (sum(x["overext"] for x in wins) / len(wins)) if wins else 0
        ap_stop = (sum(x["atr_pct"] for x in stops) / len(stops)) if stops else 0
        ap_win = (sum(x["atr_pct"] for x in wins) / len(wins)) if wins else 0
        print(f"\nbase {base}m: n={s['n']} stops={s['stops']} "
              f"wick-only={s['wick_stops']} stopped-then-target={s['stopped_then_target']} "
              f"win={s['wins']}/{s['decided']} R={s['total_r']:+.2f}")
        print(f"  avg overextension at entry: stops={ov_stop:.2f}xATR vs wins={ov_win:.2f}xATR")
        print(f"  avg ATR percentile at entry: stops={ap_stop:.0f} vs wins={ap_win:.0f}")
        print(f"  avg hours to stop: {s['avg_h_to_stop']:.1f}")
        for x in stops:
            print(f"    stop @ {datetime.fromtimestamp(x['resolved_at'], TEHRAN):%m-%d %H:%M} "
                  f"{x['direction']} wick_only={not x.get('close_through')} "
                  f"target_later={x.get('target_after_stop')} overext={x['overext']:.2f} "
                  f"atr_pct={x['atr_pct']:.0f} higher_ok={x['higher_ok']}")

    print("\n=== CANDIDATE FIXES (past data = hypotheses only) ===")
    variants = [
        ("baseline 1.5x/2R", {}),
        ("stop 2.0x", {"stop_mult": 2.0}),
        ("stop 2.5x", {"stop_mult": 2.5}),
        ("overext<=1.0 filter", {"max_overext": 1.0}),
        ("overext<=0.75 + stop2.0", {"max_overext": 0.75, "stop_mult": 2.0}),
        ("ATR pct<=80 filter", {"max_atr_pct": 80}),
        ("need higher-TF agree", {"need_higher_tf": True}),
        ("entry next candle open", {"next_open": True}),
        ("next open + stop2.0", {"next_open": True, "stop_mult": 2.0}),
    ]
    for base in (30, 60, 240):
        print(f"\nbase {base}m:")
        for name, kw in variants:
            s = summarize(run(base, **kw))
            wr = f"{s['wins']}/{s['decided']}" if s["decided"] else "-"
            print(f"  {name:26} n={s['n']:3} win={wr:5} stops={s['stops']:3} "
                  f"wick={s['wick_stops']:3} thenTgt={s['stopped_then_target']:2} "
                  f"R={s['total_r']:+6.2f}")


if __name__ == "__main__":
    main()
