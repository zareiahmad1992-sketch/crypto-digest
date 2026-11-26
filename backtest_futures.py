#!/usr/bin/env python3
"""EMA20/50 backtest on Binance USDT-M perpetual futures with Telegram alerts.

Data: Binance futures public klines.
Signal: EMA20 crosses EMA50 on a closed candle.
Entry: next candle open, with slippage.
Exit: 1.5 ATR stop or 2R target.
If both levels are touched in one candle, stop is assumed first.

Funding, liquidation, order-book liquidity and exchange downtime
are NOT modeled. Results are illustrative, not investment advice.
"""

import argparse
import time
from datetime import datetime, timedelta, timezone
import os

import requests
import trend_alerts as t


BASE_URL = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "TONUSDT")
TIMEFRAMES = ("15m", "1h", "4h")

FAST = 20
SLOW = 50
ATR_PERIOD = 14
STOP_ATR = 1.5
TARGET_R = 2.0

FEE_RATE = 0.0005       # 0.05% per side
SLIPPAGE_RATE = 0.0002  # 0.02% per side

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BitMahdiFuturesBacktest/1.0"})


def utc_date(value):
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def get_json(path, params=None):
    response = SESSION.get(
        BASE_URL + path,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def verify_symbols():
    payload = get_json("/fapi/v1/exchangeInfo")
    available = {item["symbol"]: item for item in payload.get("symbols", [])}
    for symbol in SYMBOLS:
        item = available.get(symbol)
        if not item:
            print(f"WARNING: {symbol} در فهرست فعلی صرافی پیدا نشد.")
            continue
        print(
            f"{symbol}: status={item.get('status')}, "
            f"contractType={item.get('contractType')}, "
            f"quote={item.get('quoteAsset')}"
        )


def fetch_klines(symbol, interval, start, end):
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    cursor = start_ms
    rows = []

    while cursor < end_ms:
        payload = get_json(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": 1500,
            },
        )

        if not isinstance(payload, list):
            raise ValueError(f"Unexpected API response: {payload}")

        if not payload:
            break

        for row in payload:
            ts = int(row[0])
            close_ms = int(row[6])
            if ts >= start_ms and close_ms < end_ms:
                rows.append(
                    (
                        ts // 1000,
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                    )
                )

        next_cursor = int(payload[-1][0]) + 1
        if next_cursor <= cursor:
            raise ValueError("Pagination did not advance")
        cursor = next_cursor
        time.sleep(0.15)

    unique = {row[0]: row for row in rows}
    return [unique[k] for k in sorted(unique)]


def close_trade(position, exit_price, reason):
    direction = position["direction"]
    entry = position["entry"]

    execution = exit_price * (
        1 - SLIPPAGE_RATE if direction == 1 else 1 + SLIPPAGE_RATE
    )

    gross = direction * (execution - entry) / entry

    fees = FEE_RATE + FEE_RATE * execution / entry
    return {
        "return": gross - fees,
        "reason": reason,
        "direction": direction,
    }


def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        print("توکن یا شناسه چت تلگرام تنظیم نشده است!")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"خطا در ارسال پیام به تلگرام: {e}")


def run_backtest(rows, start, end, bot_token=None, chat_id=None):
    if len(rows) < SLOW + 2:
        raise ValueError("کندل کافی برای محاسبه اندیکاتورها وجود ندارد")

    closes = [row[4] for row in rows]
    fast = t.ema_series(closes, FAST)
    slow = t.ema_series(closes, SLOW)
    volatility = t.atr_series(rows, ATR_PERIOD)

    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())

    position = None
    trades = []

    for i in range(2, len(rows)):
        ts, opening, high, low, close = rows[i]

        if ts < start_ts or ts >= end_ts:
            continue

        if position is None:
            a, b = i - 2, i - 1
            if None not in (fast[a], slow[a], fast[b], slow[b], volatility[b]):
                direction = 0
                if fast[a] <= slow[a] and fast[b] > slow[b]:
                    direction = 1
                elif fast[a] >= slow[a] and fast[b] < slow[b]:
                    direction = -1

                if direction and volatility[b] > 0:
                    entry = opening * (
                        1 + SLIPPAGE_RATE if direction == 1 else 1 - SLIPPAGE_RATE
                    )
                    distance = STOP_ATR * volatility[b]
                    stop = entry - direction * distance
                    target = entry + direction * TARGET_R * distance

                    if stop > 0 and target > 0:
                        position = {
                            "direction": direction,
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                        }
                        # ارسال پیام ورود
                        if bot_token and chat_id:
                            trend_text = "صعودی" if direction == 1 else "نزولی"
                            msg = (f"📈 ورود {trend_text}:\n"
                                   f"ورود: {entry:.2f}\n"
                                   f"حد ضرر: {stop:.2f}\n"
                                   f"هدف: {target:.2f}")
                            send_telegram_message(bot_token, chat_id, msg)

        if position is None:
            continue

        direction = position["direction"]
        stop = position["stop"]
        target = position["target"]

        if direction == 1:
            if opening <= stop:
                trades.append(close_trade(position, opening, "stop_gap"))
                # پیام خروج
                if bot_token and chat_id:
                    send_telegram_message(bot_token, chat_id,
                        f"🔴 خروج به دلیل حد ضرر (stop_gap) با قیمت {opening:.2f}")
                position = None
                continue
            if opening >= target:
                trades.append(close_trade(position, target, "target"))
                if bot_token and chat_id:
                    send_telegram_message(bot_token, chat_id,
                        f"🟢 خروج به دلیل هدف (target) با قیمت {target:.2f}")
                position = None
                continue

            hit_stop = low <= stop
            hit_target = high >= target
        else:
            if opening >= stop:
                trades.append(close_trade(position, opening, "stop_gap"))
                if bot_token and chat_id:
                    send_telegram_message(bot_token, chat_id,
                        f"🔴 خروج به دلیل حد ضرر (stop_gap) با قیمت {opening:.2f}")
                position = None
                continue
            if opening <= target:
                trades.append(close_trade(position, target, "target"))
                if bot_token and chat_id:
                    send_telegram_message(bot_token, chat_id,
                        f"🟢 خروج به دلیل هدف (target) با قیمت {target:.2f}")
                position = None
                continue

            hit_stop = high >= stop
            hit_target = low <= target

        if hit_stop:
            reason = "both_stop_first" if hit_target else "stop"
            trades.append(close_trade(position, stop, reason))
            if bot_token and chat_id:
                send_telegram_message(bot_token, chat_id,
                    f"🔴 خروج به دلیل حد ضرر با قیمت {stop:.2f}")
            position = None
        elif hit_target:
            trades.append(close_trade(position, target, "target"))
            if bot_token and chat_id:
                send_telegram_message(bot_token, chat_id,
                    f"🟢 خروج به دلیل هدف با قیمت {target:.2f}")
            position = None

    if position is not None:
        last_rows = [row for row in rows if start_ts <= row[0] < end_ts]
        if last_rows:
            trades.append(close_trade(position, last_rows[-1][4], "period_end"))
            if bot_token and chat_id:
                send_telegram_message(bot_token, chat_id,
                    f"⏳ خروج به دلیل پایان بازه با قیمت {last_rows[-1][4]:.2f}")

    return trades


def print_results(label, trades):
    count = len(trades)
    if not count:
        print(f"  {label}: بدون معامله")
        return

    wins = sum(1 for trade in trades if trade["return"] > 0)
    total = sum(trade["return"] for trade in trades)
    average = total / count
    ambiguous = sum(t["reason"] == "both_stop_first" for t in trades)
    forced = sum(t["reason"] == "period_end" for t in trades)

    print(
        f"  {label}: معاملات={count} | "
        f"برد خالص={wins / count * 100:.1f}% | "
        f"میانگین هر معامله={average * 100:+.3f}% | "
        f"جمع بازده={total * 100:+.2f}% | "
        f"برخورد همزمان={ambiguous} | پایان بازه={forced}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01", help="شروع بازه با فرمت YYYY-MM-DD، UTC")
    parser.add_argument("--split", default="2025-10-01", help="شروع بازه تست خارج از نمونه، UTC")
    parser.add_argument("--end", default="2026-01-01", help="پایان بازه، غیرشامل، UTC")
    args = parser.parse_args()

    try:
        start = utc_date(args.start)
        split = utc_date(args.split)
        end = utc_date(args.end)

        if not start < split < end:
            raise ValueError("باید start < split < end باشد")

        if end > datetime.now(timezone.utc):
            raise ValueError("تاریخ پایان نباید در آینده باشد")

        print("بررسی وضعیت فعلی قراردادها:")
        verify_symbols()

        print(
            "\nفرض‌ها: EMA20/50، استاپ 1.5 ATR، هدف 2R، "
            f"کارمزد هر طرف {FEE_RATE * 100:.3f}%, "
            f"لغزش هر طرف {SLIPPAGE_RATE * 100:.3f}%"
        )
        print("فاندینگ و لیکوییدشدن محاسبه نمی‌شوند.")
        print("جمع بازده، جمع ساده درصد معاملات است؛ بازده حساب نیست.\n")

        warmup_start = start - timedelta(days=60)

        bot_token = os.getenv("BOT_TOKEN")
        chat_id = os.getenv("CHANNEL_ID")

        for symbol in SYMBOLS:
            for interval in TIMEFRAMES:
                print(f"\n{symbol} | {interval}")
                try:
                    rows = fetch_klines(symbol, interval, warmup_start, end)
                    print(f"  تعداد کندل دریافتی: {len(rows)}")

                    if rows:
                        first = datetime.fromtimestamp(rows[0][0], timezone.utc)
                        print(f"  اولین کندل موجود: {first:%Y-%m-%d %H:%M} UTC")

                        if first > warmup_start + timedelta(days=1):
                            print(
                                "  هشدار: داده کافی برای کل بازه warm-up در دسترس نبود."
                            )

                    train = run_backtest(rows, start, split, bot_token, chat_id)
                    test = run_backtest(rows, split, end, bot_token, chat_id)

                    print_results("بازه اولیه", train)
                    print_results("تست خارج از نمونه", test)

                except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
                    print(f"  خطا: {exc}")

        return 0

    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
