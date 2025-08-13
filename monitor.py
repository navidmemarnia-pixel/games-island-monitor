#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, json, logging
from datetime import datetime, timezone
from typing import Set, List, Tuple, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

CATEGORY_URL = os.environ.get(
    "GI_CATEGORY_URL",
    "https://games-island.eu/c/Magic-The-Gathering/MtG-Booster-Displays-englisch",
)
STATE_FILE = os.environ.get("GI_STATE_FILE", "games_island_state.json")

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "").strip()
EMAIL_TO = os.environ.get("EMAIL_TO", "navid.memarnia@gmail.com").strip()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")

def http_get(url: str, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache", "Pragma": "no-cache",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp

def normalize_url(base: str, href: str) -> Optional[str]:
    if not href: return None
    href = href.strip()
    if href.startswith("#") or "javascript:" in href: return None
    abs_url = urljoin(base, href)
    if urlparse(abs_url).netloc not in {"games-island.eu","www.games-island.eu"}:
        return None
    return abs_url

PRODUCT_PATTERNS = [
    re.compile(r"/MtG-", re.IGNORECASE),
    re.compile(r"/Magic-The-Gathering", re.IGNORECASE),
    re.compile(r"Booster-(Box|Display)", re.IGNORECASE),
]

def looks_like_product(path: str) -> bool:
    if any(seg in path for seg in ["/c/","/en/c/","/m/","/Home","/search","/?"]):
        return False
    for pat in PRODUCT_PATTERNS:
        if pat.search(path): return True
    if "/" in path and "." not in path and len(path.strip("/").split("/")) == 1:
        if len(path.strip("/")) > 8: return True
    return False

def extract_product_links(html: str, base_url: str) -> List[Tuple[str,str]]:
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        abs_url = normalize_url(base_url, a["href"])
        if not abs_url: continue
        path = urlparse(abs_url).path
        if looks_like_product(path):
            title = (a.get_text(strip=True) or abs_url).strip()
            if abs_url not in seen:
                links.append((abs_url, title)); seen.add(abs_url)
    return links

def load_state() -> Set[str]:
    if not os.path.exists(STATE_FILE): return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("product_urls", []))
    except Exception as e:
        logging.warning("Konnte State nicht laden: %s", e); return set()

def save_state(urls: Set[str]) -> None:
    payload = {"saved_at": datetime.now(timezone.utc).isoformat(),
               "product_urls": sorted(urls)}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def diff_links(old: Set[str], new: Set[str]) -> List[str]:
    return sorted(new - old)

def send_email(subject: str, body: str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_FROM and EMAIL_TO):
        logging.error("E-Mail nicht konfiguriert.")
        return False
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formatdate
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject; msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO; msg["Date"] = formatdate(localtime=True)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        logging.info("E-Mail versendet an %s", EMAIL_TO); return True
    except Exception as e:
        logging.error("E-Mail-Fehler: %s", e); return False

def notify_new_items(new_urls: List[str]) -> None:
    if not new_urls:
        logging.info("Keine neuen Produkte gefunden."); return
    lines = ["Neue Produkte bei Games Island entdeckt:", ""]
    lines += [f"• {u}" for u in new_urls]
    send_email("Games Island – Neue Einträge", "\n".join(lines))

def main() -> int:
    try:
        resp = http_get(CATEGORY_URL)
    except Exception as e:
        logging.error("HTTP-Fehler: %s", e); return 2
    links = extract_product_links(resp.text, CATEGORY_URL)
    current_urls = {u for (u, _t) in links}
    if not current_urls:
        logging.warning("Konnte keine Produkt-Links erkennen.")
    prev_urls = load_state()
    first_run = len(prev_urls) == 0
    new = diff_links(prev_urls, current_urls)
    if first_run:
        logging.info("Erstlauf – speichere (%d Links).", len(current_urls))
        save_state(current_urls)
        if os.environ.get("NOTIFY_ON_FIRST_RUN") == "1":
            notify_new_items(sorted(current_urls))
        return 0
    if new:
        logging.info("Neue Produkte: %d", len(new))
        notify_new_items(new)
        save_state(prev_urls.union(new))
    else:
        logging.info("Keine neuen Produkte seit letztem Check.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
