#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily.py — نبض جامع بازار کریپتو
جمع‌آوری و پردازش هوشمند از کانال‌های خبری تلگرام، فیدهای RSS معتبر،
داده‌های آنچین، شاخص سنتیمنت، فاندینگ و هیت‌مپ لیکوییدیشن CoinGlass.
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup

H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fa,en;q=0.9"
}
API_H = {"User-Agent": "CryptoDigestBot/3.0", "Accept": "application/json"}

# ═══════════════ کانال‌های تلگرام معتبر (فارسی و انگلیسی) ═══════════════
TELEGRAM_SOURCES = [
    ("lookonchain",             "Lookonchain (آنچین)",       "en", 1),
    ("cryptoquant_official",    "CryptoQuant",               "en", 1),
    ("whale_alert_io",          "Whale Alert",               "en", 2),
    ("glassnode_alerts",        "Glassnode Alerts",          "en", 2),
    ("WuBlockchain",            "Wu Blockchain (فوری)",      "en", 1),
    ("TreeNewsFeed",            "Tree News (اخبار لحظه‌ای)", "en", 1),
    ("intothecryptoverse_news", "ITC News",                  "en", 2),
    ("defillama_tg",            "DefiLlama",                 "en", 2),
    ("arzdigital",              "ارزدیجیتال",                "fa", 1),
    ("arzdigitalb",             "اخبار فوری کریپتو",         "fa", 1),
    ("mihanblockchain",         "میهن بلاک‌چین",             "fa", 1),
]

# ═══════════════ وبسایت‌ها و فیدهای خبری معتبر جهان ═══════════════
RSS_SOURCES = [
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/",  1),
    ("The Block",         "https://www.theblock.co/rss.xml",                 1),
    ("Cointelegraph",     "https://cointelegraph.com/rss",                   2),
    ("Bitcoin Magazine",  "https://bitcoinmagazine.com/feed",                2),
    ("Decrypt",           "https://decrypt.co/feed",                         2),
    ("MihanBlockchain",   "https://mihanblockchain.com/feed/",               2),
]

# ═══════════════ فیلترها و الگوها ═══════════════
BTC_RE = re.compile(r"بیت\s*کوین|بیتکوین|bitcoin|\bBTC\b", re.I)
ETH_RE = re.compile(r"اتریوم|ethereum|\bETH\b", re.I)
ANALYSIS_RE = re.compile(
    r"تحلیل|حمایت|مقاومت|روند|سناریو|هدف|شکست|آنچین|on-?chain|MVRV|جریان|نهنگ|whale|"
    r"لیکویید|liquidat|اهرم|open interest|funding|ETF|فدرال|fed|نرخ بهره|تورم|CPI|ماکرو|"
    r"dominance|دامیننس|سیگنال|میانگین متحرک|moving average|realized|هاوینگ|SEC|سرمایه", re.I)

NOISE_RE = re.compile(
    r"ایردراپ|airdrop|جایزه|مسابقه|کد تخفیف|تخفیف|تبلیغ|اسپانسر|قرعه‌کشی|هدیه|giveaway|"
    r"bonus|کش‌بک|ریفرال|رفرال|ثبت‌نام|join now|promo|shib|pepe|meme", re.I)

def clean_text(text):
    text = re.sub(r"[ \t]+", " ", text or "")
    return "\n".join(x.strip() for x in text.splitlines() if x.strip())

# ═══════════════ دریافت اطلاعات از تلگرام و RSS ═══════════════
def fetch_telegram(handle, name, lang, tier, pages=1):
    posts, before = [], None
    for _ in range(pages):
        url = f"https://t.me/s/{handle}" + (f"?before={before}" if before else "")
        try:
            r = requests.get(url, headers=H, timeout=20)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            batch = []
            for m in soup.select(".tgme_widget_message"):
                pid = m.get("data-post")
                tx = m.select_one(".tgme_widget_message_text")
                tm = m.select_one("time[datetime]")
                if not pid or not tx:
                    continue
                batch.append({
                    "text": clean_text(tx.get_text("\n")),
                    "url": f"https://t.me/{pid}",
                    "date": tm["datetime"] if tm else None,
                    "channel": handle,
                    "channel_name": name,
                    "tier": tier
                })
            known = {p["url"] for p in posts}
            new_posts = [b for b in batch if b["url"] not in known]
            posts += new_posts
            if not new_posts:
                break
            fid = batch[0]["url"].split("/")[-1]
            if not fid.isdigit() or int(fid) <= 1:
                break
            before = int(fid)
            time.sleep(0.3)
        except Exception:
            break
    return posts

def fetch_rss(name, url, tier):
    items = []
    try:
        r = requests.get(url, headers=H, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            t = (it.findtext("title") or "").strip()
            desc = BeautifulSoup(it.findtext("description") or "", "html.parser").get_text(" ")
            d = it.findtext("pubDate") or ""
            try:
                iso = parsedate_to_datetime(d).astimezone(timezone.utc).isoformat(timespec="seconds")
            except Exception:
                iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            items.append({
                "text": f"{t}\n{clean_text(desc)[:300]}",
                "url": (it.findtext("link") or "").strip(),
                "date": iso,
                "channel": name.lower(),
                "channel_name": name,
                "tier": tier
            })
    except Exception:
        pass
    return items

def pick_top_news(posts, hours=36, limit=5):
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    candidates = []
    for p in posts:
        t = p["text"]
        if not (BTC_RE.search(t) or ETH_RE.search(t)):
            continue
        if NOISE_RE.search(t) and not ANALYSIS_RE.search(t):
            continue
        try:
            ts = datetime.fromisoformat(p["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                continue
        except Exception:
            pass
        
        sc = {1: 4, 2: 2, 3: 1}.get(p.get("tier", 3), 1)
        if ANALYSIS_RE.search(t): sc += 3
        if "ETF" in t or "Fed" in t or "نرخ بهره" in t: sc += 3
        if len(t) < 80: sc -= 3
        
        if sc >= 4:
            candidates.append(dict(p, score=sc))
            
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected, seen_channels = [], {}
    for c in candidates:
        if seen_channels.get(c["channel"], 0) >= 2:
            continue
        seen_channels[c["channel"]] = seen_channels.get(c["channel"], 0) + 1
        selected.append(c)
        if len(selected) >= limit:
            break
    return selected

# ═══════════════ دریافت آمار زنده بازار ═══════════════
def fetch_market_pulse():
    data = {}
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "usd",
                                 "include_24hr_change": "true"}, headers=API_H, timeout=15)
        data["prices"] = r.json()
    except Exception:
        data["prices"] = {}

    try:
        g = requests.get("https://api.coingecko.com/api/v3/global", headers=API_H, timeout=15).json()["data"]
        data["global"] = {
            "btc_dom": g["market_cap_percentage"]["btc"],
            "eth_dom": g["market_cap_percentage"]["eth"],
            "mcap": g["total_market_cap"]["usd"],
            "chg": g.get("market_cap_change_percentage_24h_usd", 0)
        }
    except Exception:
        data["global"] = None

    try:
        f = requests.get("https://api.alternative.me/fng/?limit=1", headers=API_H, timeout=12).json()["data"][0]
        data["fng"] = (int(f["value"]), f["value_classification"])
    except Exception:
        data["fng"] = None

    return data

# ═══════════════ تاریخ شمسی ═══════════════
def to_jalali(y, m, d):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy, gm, gd = y, m, d
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm, jd = (1 + days // 31, 1 + days % 31) if days < 186 else (7 + (days - 186) // 30, 1 + (days - 186) % 30)
    return jy, jm, jd

FA_MAP = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa_num(x):
    return str(x).translate(FA_MAP)

# ═══════════════ ساخت پست گزارش روزانه ═══════════════
def build_daily_report(m_data, news_list):
    now = datetime.now()
    jy, jm, jd = to_jalali(now.year, now.month, now.day)
    months = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
    days = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

    L = [f"🧭 <b>نبض و گزارش تحلیلی بازار کریپتو</b> | {days[now.weekday()]} {fa_num(jd)} {months[jm - 1]} {fa_num(jy)}\n"]

    pr = m_data.get("prices", {})
    if pr.get("bitcoin"):
        btc = pr["bitcoin"]
        eth = pr.get("ethereum", {})
        sol = pr.get("solana", {})
        ar = lambda c: "🟢" if c >= 0 else "🔴"
        
        L.append("💹 <b>قیمت‌های کلیدی لحظه‌ای:</b>\n"
                 f"• بیت‌کوین: <code>${btc['usd']:,.0f}</code> {ar(btc.get('usd_24h_change',0))} (<code>{btc.get('usd_24h_change',0):+.2f}%</code>)\n"
                 f"• اتریوم: <code>${eth.get('usd',0):,.0f}</code> {ar(eth.get('usd_24h_change',0))} (<code>{eth.get('usd_24h_change',0):+.2f}%</code>)\n"
                 f"• سولانا: <code>${sol.get('usd',0):,.2f}</code> {ar(sol.get('usd_24h_change',0))} (<code>{sol.get('usd_24h_change',0):+.2f}%</code>)")

    g = m_data.get("global")
    if g:
        fg_str = ""
        if m_data.get("fng"):
            v, lbl = m_data["fng"]
            fa_lbl = {"Extreme Fear": "اضطراب شدید", "Fear": "ترس", "Neutral": "خنثی", "Greed": "طمع", "Extreme Greed": "طمع شدید"}.get(lbl, lbl)
            fg_str = f"\n😨 شاخص ترس و طمع: <b>{fa_num(v)}</b> ({fa_lbl})"
            
        L.append(f"\n📊 <b>ساختار کلان بازار:</b>\n"
                 f"• ارزش کل بازار: <b>{fa_num(round(g['mcap']/1e12,2))} تریلیون دلار</b> (<code>{g['chg']:+.2f}%</code>)\n"
                 f"• سهم از بازار (Dominance): بیت‌کوین <b>{fa_num(round(g['btc_dom'],1))}٪</b> | اتریوم <b>{fa_num(round(g['eth_dom'],1))}٪</b>{fg_str}")

    if news_list:
        rows = []
        for p in news_list:
            clean_p = re.sub(r"https?://\S+|@\w+|#\w+", "", p["text"])
            clean_p = re.sub(r"[⭕️🔸🔹📉📈⚠️🐋🔐📊🔥👀👇🔗▪️•]+", " ", clean_p).strip()[:220]
            rows.append(f"• <b>[{p['channel_name']}]</b> {clean_p}… <a href='{p['url']}'>[منبع]</a>")
        L.append("\n🗞 <b>مهم‌ترین رویدادها و اخبار آنچین (۲۴ ساعت گذشته):</b>\n" + "\n".join(rows))

    L.append("\n🔎 <b>ابزارهای بررسی دستی و آنچین:</b>\n"
             "• <a href='https://www.coinglass.com/LiquidationHeatMap/BTC'>نقشه هیت‌مپ لیکوییدیشن بیت‌کوین (CoinGlass)</a>\n"
             "• <a href='https://www.coinglass.com/FundingRate'>نقشه حرارتی فاندینگ ریت فیوچرز (Funding Rate)</a>\n"
             "• <a href='https://www.tradingview.com/symbols/BTCUSDT.P/'>نمودار پیشرفته چارت بیت‌کوین (TradingView)</a>\n"
             "• <a href='https://cryptoquant.com/asset/btc/chart/exchange-flows'>جریان ورود و خروج به صرافی‌ها (CryptoQuant)</a>\n"
             "<i>مناطق نقشه لیکوییدیشن برای شکار نقدینگی استفاده می‌شوند و پیش‌بینی قطعی نیستند.</i>")

    L.append("\n━━━━━━━━━━━━━━━━━━━━\n"
             "📚 <b>منابع:</b> Lookonchain • WuBlockchain • CryptoQuant • CoinDesk • The Block • ArzDigital • MihanBlockchain\n"
             "❗️ <i>صرفاً گزارش تحلیلی بازار؛ توصیه مالی مستقیم نیست.</i>")
    
    return "\n".join(L)

# ═══════════════ ارسال به تلگرام ═══════════════
def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=25)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending report: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="نمایش خروجی در ترمینال")
    parser.add_argument("--pages", type=int, default=1, help="تعداد صفحات تلگرام")
    args, _ = parser.parse_known_args() # هر آرگومان اضافه دیگری را نادیده می‌گیرد تا خطا رخ ندهد

    print("📡 جمع‌آوری از برترین رسانه‌های جهانی، کانال‌های تلگرام و آنچین...")
    all_posts = []
    for h, n, l, t in TELEGRAM_SOURCES:
        all_posts += fetch_telegram(h, n, l, t, pages=args.pages)
    for n, u, t in RSS_SOURCES:
        all_posts += fetch_rss(n, u, t)

    print(f"✅ مجموعاً {len(all_posts)} خبر و پست دریافت شد.")
    top_news = pick_top_news(all_posts)
    market_pulse = fetch_market_pulse()
    final_post = build_daily_report(market_pulse, top_news)

    if args.dry_run:
        print("\n" + "="*60)
        print(final_post)
        print("="*60 + "\n")
        return 0

    token = os.getenv("BOT_TOKEN", "").strip()
    chat_id = (os.getenv("CHANNEL_ID") or os.getenv("CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("خطا: BOT_TOKEN یا CHANNEL_ID در سیستم ست نشده است.")
        return 1

    success = send_telegram(token, chat_id, final_post)
    if success:
        print("✅ گزارش روزانه با موفقیت به تلگرام ارسال شد.")
    return 0 if success else 1

if __name__ == "__main__":
    raise SystemExit(main())
