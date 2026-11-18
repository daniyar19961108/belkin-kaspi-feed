#!/usr/bin/env python3
"""
Сборка XML-прайс-листа Kaspi для Belkin kz. Запускается GitHub Actions каждые 30 минут.

  * цены и названия — файл prices.csv в этом репозитории (Code, Name, Price)
  * остатки PP12    — фид поставщика Asbis (sku = Code, без учёта регистра)

Если фид Asbis недоступен или подозрительно мал, скрипт падает и старый фид остаётся на месте.
Только стандартная библиотека Python.
"""
import csv
import datetime as dt
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

PRICES_FILE = os.environ.get("PRICES_FILE", "prices.csv")
ASBIS_URL = os.environ.get("ASBIS_URL", "https://wsptech.mktx.io/storage/feeds/asbis.xml")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "kaspi_feed.xml")

COMPANY = "Belkin kz"
MERCHANT_ID = "30487443"
BRAND = "Belkin"
STORE = "PP12"
MIN_PRICE_ROWS = 10
MIN_SUPPLIER_OFFERS = int(os.environ.get("MIN_SUPPLIER_OFFERS", "1000"))
ALMATY = dt.timezone(dt.timedelta(hours=5))


def fetch(url, src, tries=3):
    if os.path.exists(url):
        with open(url, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "belkin-kaspi-feed"})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"Не удалось скачать {src}: {last}")


def to_int(v):
    s = re.sub(r"[^\d\-]", "", str(v or ""))
    return int(s) if s not in ("", "-") else None


def norm(code):
    return str(code or "").strip().upper()


def read_prices():
    items = {}
    with open(PRICES_FILE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = norm(r.get("Code"))
            price = to_int(r.get("Price"))
            if not code or not price or price <= 0:
                continue
            items[code] = {"name": (r.get("Name") or "").strip() or code, "price": price}
    if len(items) < MIN_PRICE_ROWS:
        raise RuntimeError(f"В prices.csv всего {len(items)} товаров с ценой: фид не обновлён.")
    return items


def read_asbis():
    root = ET.fromstring(fetch(ASBIS_URL, "фид Asbis"))
    stock = {}
    for offer in root.iter():
        if not offer.tag.endswith("offer"):
            continue
        qty = 0
        for a in offer.iter():
            if a.tag.endswith("availability") and a.get("available") in ("yes", "да"):
                qty += to_int(a.get("stockCount")) or 1
        code = norm(offer.get("sku"))
        stock[code] = stock.get(code, 0) + qty
    if len(stock) < MIN_SUPPLIER_OFFERS:
        raise RuntimeError(f"В фиде Asbis всего {len(stock)} товаров: фид не обновлён.")
    return stock


def availability(qty):
    if qty > 0:
        return f'<availability available="yes" storeId="{STORE}" stockCount="{qty}"/>'
    return f'<availability available="no" storeId="{STORE}"/>'


def build(items, stock):
    now = dt.datetime.now(ALMATY).strftime("%Y-%m-%d %H:%M")
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<kaspi_catalog date="{now}" xmlns="kaspiShopping" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="kaspiShopping http://kaspi.kz/kaspishopping.xsd">',
        f"  <company>{escape(COMPANY)}</company>",
        f"  <merchantid>{escape(MERCHANT_ID)}</merchantid>",
        "  <offers>",
    ]
    for code, it in items.items():
        out += [
            f"    <offer sku={quoteattr(code)}>",
            f"      <model>{escape(it['name'])}</model>",
            f"      <brand>{BRAND}</brand>",
            "      <availabilities>",
            "        " + availability(stock.get(code, 0)),
            "      </availabilities>",
            f"      <price>{it['price']}</price>",
            "    </offer>",
        ]
    out += ["  </offers>", "</kaspi_catalog>", ""]
    return "\n".join(out)


def main():
    items = read_prices()
    stock = read_asbis()
    xml = build(items, stock)
    ET.fromstring(xml.encode("utf-8"))  # проверка валидности до записи
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(xml)
    os.replace(tmp, OUTPUT_FILE)
    in_stock = sum(1 for c in items if stock.get(c, 0) > 0)
    missing = [c for c in items if c not in stock]
    print(f"Товаров: {len(items)}, в наличии: {in_stock}")
    if missing:
        print("Нет в фиде Asbis:", ", ".join(missing))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ОШИБКА:", e, file=sys.stderr)
        sys.exit(1)
