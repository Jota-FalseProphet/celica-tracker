#!/usr/bin/env python3
"""Recolecta precios de Toyota Celica 2002-2006 en España (Autoscout24).
Wallapop / Coches.net requieren navegador (SPA / anti-bot).
"""
import csv, datetime, json, os, re, sys, time, urllib.parse, urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def autoscout24_pages():
    """Trae todas las Celicas en venta en España (~17). Filtraremos
    2002-2006 al graficar; el resto sirve de contexto generacional."""
    base = "https://www.autoscout24.es/lst/toyota/celica"
    qs = {"atype": "C", "cy": "E",
          "desc": 0, "sort": "price", "source": "listpage_pagination"}
    rows, page, num_pages = [], 1, 1
    while page <= num_pages:
        q = dict(qs); q["page"] = page
        url = base + "?" + urllib.parse.urlencode(q)
        html = fetch(url)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            break
        data = json.loads(m.group(1))
        pp = data["props"]["pageProps"]
        num_pages = pp.get("numberOfPages") or 1
        for l in pp.get("listings", []):
            v = l.get("vehicle", {})
            t = l.get("tracking", {})
            loc = l.get("location") or {}
            price = l.get("price")
            price_eur = None
            if isinstance(price, dict):
                pf = price.get("priceFormatted", "")
                m2 = re.search(r"([\d.]+)", pf.replace(".", ""))
                if m2:
                    try: price_eur = int(m2.group(1))
                    except: pass
            elif isinstance(price, str):
                m2 = re.search(r"\d+", price.replace(".", ""))
                if m2: price_eur = int(m2.group(0))
            first_reg = t.get("firstRegistration") or ""
            year = None
            if "-" in first_reg:
                try: year = int(first_reg.split("-")[1])
                except: pass
            mileage = t.get("mileage")
            try: mileage = int(mileage) if mileage else None
            except: mileage = None
            rows.append({
                "fuente": "autoscout24",
                "id": l.get("identifier") or l.get("id"),
                "precio_eur": price_eur,
                "anio": year,
                "km": mileage,
                "modelo": v.get("modelVersionInput"),
                "combustible": v.get("fuel"),
                "transmision": v.get("transmission"),
                "ciudad": loc.get("city"),
                "cp": loc.get("zip"),
                "url": "https://www.autoscout24.es" + (l.get("url") or ""),
            })
        page += 1
        time.sleep(1)
    return rows

def main():
    today = datetime.date.today().isoformat()
    rows = autoscout24_pages()
    print(f"[{today}] Autoscout24: {len(rows)} anuncios")
    file_exists = os.path.exists(CSV_PATH)
    fields = ["fecha","fuente","id","precio_eur","anio","km","modelo",
              "combustible","transmision","ciudad","cp","url"]
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists: w.writeheader()
        for r in rows:
            r["fecha"] = today
            w.writerow(r)
    print(f"Guardado en {CSV_PATH}")
    return rows

if __name__ == "__main__":
    main()
