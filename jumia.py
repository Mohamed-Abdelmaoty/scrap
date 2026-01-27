from bs4 import BeautifulSoup
from curl_cffi import requests
import time
import json
import os
import random

# ---------------- CONFIG ----------------
BASE_URL = os.getenv(
    "BASE_URL",
    "https://www.jumia.com.eg/mens-jackets-coats/defacto/?sort=lowest-price&page={page}#catalog-listing"
)
PAGES_TO_SCRAPE = int(os.getenv("PAGES_TO_SCRAPE", 6))
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", 550))
DISCOUNT_THRESHOLD = int(os.getenv("DISCOUNT_THRESHOLD", 20))
MIN_PRICE_DROP = float(os.getenv("MIN_PRICE_DROP", 30))
HISTORY_FILE = "sent_deals.json"

SKIP_KEYWORDS = [
    "jean", "bermuda", "shorts", "pants",
    "t-shirt", "polo", "hoodie",
    "sweatshirt", "cardigan", "vest"
]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

# ---------------- PROXIES ----------------
def get_proxies():
    raw = os.getenv("PROXY_LIST", "")
    if not raw:
        return []
    # Split by newline or comma
    return [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]

PROXIES = get_proxies()

# ---------------- HELPERS ----------------
def load_history():
    if not os.path.exists(HISTORY_FILE): return {}
    try:
        with open(HISTORY_FILE, "r") as f: return json.load(f)
    except: return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=2)

def get_price_value(price_str):
    try:
        if "-" in price_str: price_str = price_str.split("-")[0]
        return float(price_str.replace("EGP", "").replace(",", "").strip())
    except: return 0.0

def get_percentage_value(perc_str):
    try: return int(perc_str.replace("%", "").strip())
    except: return 0

# ---------------- SCRAPING ----------------
def fetch_page(session, page):
    print(f"--- Scraping Page {page} ---", flush=True)

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    # Choose a random proxy each request if available
    proxy = random.choice(PROXIES) if PROXIES else None
    proxies = {"http": proxy, "https": proxy} if proxy else None
    if proxy:
        print(f"Using proxy: {proxy}", flush=True)
    else:
        print("No proxies configured, using direct connection.", flush=True)

    for attempt in range(3):
        try:
            response = session.get(
                BASE_URL.format(page=page),
                headers=headers,
                timeout=30,
                proxies=proxies
            )
            if response.status_code == 403:
                wait = 40 + (attempt * 30)
                if proxy:
                    print(f"⚠️  403 Forbidden with proxy {proxy}. Retrying in {wait}s...", flush=True)
                    proxy = random.choice(PROXIES)  # rotate proxy
                    proxies = {"http": proxy, "https": proxy}
                else:
                    print(f"⚠️  403 Forbidden (Direct). Retrying in {wait}s...", flush=True)
                time.sleep(wait)
                continue

            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            
            products = []
            for product in soup.find_all("article", class_="prd"):
                if product.find("div", class_="bdg _oos _xs"): continue
                
                name_tag = product.find("h3", class_="name")
                price_tag = product.find("div", class_="prc")
                link_tag = product.find("a", class_="core")
                
                if not name_tag or not price_tag or not link_tag: continue
                
                name = name_tag.text.strip()
                if any(word in name.lower() for word in SKIP_KEYWORDS): continue
                
                old_price = product.find("div", class_="old")
                perc = product.find("div", class_="bdg _dsct _sm")
                img = product.find("img", class_="img")

                products.append({
                    "name": name,
                    "price": price_tag.text.strip(),
                    "discount": old_price.text.strip() if old_price else "",
                    "percentage": perc.text.strip() if perc else "",
                    "image": img.get("data-src") or img.get("src") if img else "",
                    "link": f"https://www.jumia.com.eg/ar{link_tag['href']}"
                })
            print(f"✅ Found {len(products)} products on page {page}", flush=True)
            return products
        except Exception as e:
            msg = f"❌ Error on page {page} with proxy {proxy}" if proxy else f"❌ Error on page {page} (Direct)"
            print(f"{msg}: {e}", flush=True)
            time.sleep(10)
    return []

# ---------------- TELEGRAM ----------------
def send_telegram_message(deals):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing. Skipping alert.", flush=True)
        return

    url_photo = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    url_text = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for i, d in enumerate(deals[:3]):
        label = "🔥 <b>TOP DEAL</b> 🔥" if i == 0 else "📌 <b>Hot Deal</b>"
        old_price_str = f" <s>{d['discount']}</s>" if d.get('discount') else ""
        caption = (
            f"{label}\n"
            f"<b>{d['name']}</b>\n"
            f"💰 Price: <b>{d['price']}</b>{old_price_str} ({d['percentage']})\n"
            f"🔗 <a href='{d['link']}'>View on Jumia</a>"
        )
        try:
            if d.get('image'):
                requests.post(url_photo, data={"chat_id": TELEGRAM_CHAT_ID, "photo": d['image'], "caption": caption, "parse_mode": "HTML"})
            else:
                requests.post(url_text, data={"chat_id": TELEGRAM_CHAT_ID, "text": caption, "parse_mode": "HTML"})
        except: pass

    if len(deals) > 3:
        summary = ["\n<b>⚡ Even More Deals:</b>\n"]
        for d in deals[3:10]:
            summary.append(f"• <a href='{d['link']}'>{d['name']}</a> - <b>{d['price']}</b>")
        requests.post(url_text, data={"chat_id": TELEGRAM_CHAT_ID, "text": "\n".join(summary), "parse_mode": "HTML", "disable_web_page_preview": True})

# ---------------- MAIN ----------------
def main():
    print("🚀 Starting Jumia Scraper...", flush=True)
    start_time = time.time()
    all_products = []

    with requests.Session(impersonate="chrome120") as session:
        for page in range(1, PAGES_TO_SCRAPE + 1):
            page_products = fetch_page(session, page)
            all_products.extend(page_products)
            if not page_products: break

    if not all_products:
        print("No products found (likely blocked).", flush=True)
        return

    all_products.sort(key=lambda x: get_price_value(x["price"]))

    discovered = [
        p for p in all_products
        if get_price_value(p["price"]) <= PRICE_THRESHOLD
        or get_percentage_value(p["percentage"]) >= DISCOUNT_THRESHOLD
    ]

    history = load_history()
    new_deals = []

    for d in discovered:
        link = d["link"]
        new_p = get_price_value(d["price"])
        old_p = float(history.get(link, new_p + MIN_PRICE_DROP + 1))
        
        if link not in history or old_p - new_p >= MIN_PRICE_DROP:
            new_deals.append(d)
            history[link] = new_p

    if new_deals:
        send_telegram_message(new_deals)
        save_history(history)
        print(f"✅ Success! Sent {len(new_deals)} deals.", flush=True)
    else:
        print("No new deals found to alert.", flush=True)

    print(f"Done in {time.time() - start_time:.2f}s", flush=True)

if __name__ == "__main__":
    main()
