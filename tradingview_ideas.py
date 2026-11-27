import os
import re
import json
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DATA_FILE = "data/sent_tv_ideas.json"

os.makedirs("data", exist_ok=True)

def load_sent():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_sent(sent_set):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_set)[-200:], f, ensure_ascii=False, indent=2)

def send_telegram_photo(photo_url, caption):
    if not BOT_TOKEN or not CHANNEL_ID:
        print("[Preview Idea]:", caption)
        return True
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHANNEL_ID,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending photo to TG: {e}")
        return False

def fetch_tv_ideas(symbol_slug, asset_name, asset_tag):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    url = f"https://www.tradingview.com/symbols/{symbol_slug}/ideas/?type=trade&sort=popular"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select("article, div[data-card-type='idea']")
        ideas = []
        for c in cards[:4]:
            link_tag = c.select_one("a[href*='/chart/']")
            title_tag = c.select_one("a[href*='/chart/']")
            img_tag = c.select_one("img[src*='userpics'], img[src*='tradingview.com']")
            
            if not link_tag:
                continue
                
            href = link_tag.get("href", "")
            match = re.search(r'/chart/[^/]+/([a-zA-Z0-9]+)-', href)
            idea_id = match.group(1) if match else href
            
            title = link_tag.get_text(strip=True)
            if not title:
                continue
                
            # TradingView CDN Chart snapshot URL
            img_src = f"https://s3.tradingview.com/{idea_id[0].lower()}/{idea_id}_big.png" if len(idea_id) > 2 else ""
            
            ideas.append({
                "id": idea_id,
                "title": title,
                "link": f"https://www.tradingview.com{href}" if href.startswith("/") else href,
                "img": img_src,
                "asset_name": asset_name,
                "asset_tag": asset_tag
            })
        return ideas
    except Exception as e:
        print(f"Error scraping TV {symbol_slug}: {e}")
        return []

def main():
    sent_ideas = load_sent()
    targets = [
        ("XAUUSD", "طلا جهانی (انس)", "#GOLD #XAUUSD"),
        ("BTCUSD", "بیت‌کوین (BTC)", "#BITCOIN #BTC"),
        ("EURUSD", "یورو / دلار (EURUSD)", "#FOREX #EURUSD")
    ]
    
    new_sent = 0
    for slug, name, tag in targets:
        ideas = fetch_tv_ideas(slug, name, tag)
        for item in ideas:
            if item["id"] in sent_ideas:
                continue
                
            caption = (
                f"💡 📊 <b>[ایده برتر معاملاتی تریدینگ‌ویو]</b>\n\n"
                f"🔹 <b>دارایی:</b> {item['asset_name']}\n"
                f"📝 <b>عنوان تحلیل:</b> <code>{item['title'][:120]}</code>\n\n"
                f"🔗 <a href=\"{item['link']}\">مشاهده کامل ایده و تحلیل در TradingView</a>\n\n"
                f"<i>⚠️ ایده‌های تریدینگ‌ویو صرفاً جنبه آموزشی دارند و پیشنهاد مستقیم ورود نیستند.</i>\n\n"
                f"{item['asset_tag']} #TradingView #چارت_تحلیلی"
            )
            
            if item["img"]:
                sent_ok = send_telegram_photo(item["img"], caption)
            else:
                sent_ok = False
                
            if sent_ok:
                sent_ideas.add(item["id"])
                new_sent += 1
                break  # ارسال بهترین ایده از هر دارایی در هر چرخه
                
    save_sent(sent_ideas)
    print(f"TradingView scan complete. Sent {new_sent} new ideas.")

if __name__ == "__main__":
    main()
