#!/usr/bin/env python3
"""Append-only Kraken candle archive for BTC/USD (30m, 1h, 4h, 1d).

Each run merges the latest 720 closed candles into data/history/btc_<iv>.csv.
Running it from GitHub Actions every 30 minutes grows a multi-month history
so backtests stop being limited to Kraken's 720-candle public window.
"""
import csv
import os
import sys
import time
from pathlib import Path

import trend_alerts as t

HIST = Path(os.getenv("HISTORY_DIR", "data/history"))
INTERVALS = (30, 60, 240, 1440)


def load(path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {int(r["ts"]): (int(r["ts"]), float(r["o"]), float(r["h"]),
                               float(r["l"]), float(r["c"]))
                for r in csv.DictReader(fh)}


def save(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ts", "o", "h", "l", "c"])
        for row in sorted(rows.values()):
            writer.writerow(row)
    tmp.replace(path)


def fetch_closed(interval):
    payload = t.SESSION.get(t.API, params={"pair": "XBTUSD", "interval": interval},
                            timeout=25).json()
    if payload.get("error"):
        raise ValueError(payload["error"])
    rows = list(payload["result"].values())[0]
    rows = [(int(r[0]), *(float(x) for x in r[1:5])) for r in rows]
    now = time.time()
    return [r for r in rows if r[0] + interval * 60 <= now + 60]


def update(interval):
    path = HIST / f"btc_{interval}.csv"
    old = load(path)
    new = fetch_closed(interval)
    added = 0
    for row in new:
        if row[0] not in old:
            old[row[0]] = row
            added += 1
    save(path, old)
    return added, len(old)


def main():
    total = 0
    for interval in INTERVALS:
        try:
            added, count = update(interval)
            total += added
            print(f"interval {interval}m: +{added} new, {count} total")
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            print(f"interval {interval}m FAILED: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
        time.sleep(1)
    if total == 0 and not any((HIST / f"btc_{iv}.csv").exists() for iv in INTERVALS):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
