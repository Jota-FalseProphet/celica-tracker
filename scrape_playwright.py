#!/usr/bin/env python3
"""Scraper con Playwright para fuentes que requieren navegador real:
- Coches.net (SPA + auth)
- Wallapop (SPA + auth)

Usa el mismo CSV que scrape.py. La columna 'fuente' diferencia el origen.
"""
import csv, datetime, os, re, sys, time
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

def _to_int(s):
    if s is None: return None
    m = re.search(r"\d[\d.]*", str(s).replace("\xa0", " "))
    if not m: return None
    return int(m.group(0).replace(".", ""))

def scrape_coches(page, year_from=2002, year_to=2006):
    url = (f"https://www.coches.net/segunda-mano/?MakeIds%5B0%5D=66"
           f"&ModelIds%5B0%5D=412&YearFrom={year_from}&YearTo={year_to}")
    print(f"  → {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # aceptar cookies si aparece
    try:
        page.locator("button:has-text('Aceptar')").first.click(timeout=3000)
    except: pass
    try:
        page.wait_for_selector("article, .mt-CardAd, [data-ad-id], a[href*='/coches-segunda-mano/']", timeout=20000)
    except:
        print("  ! coches.net: no cargaron listings")
        return []
    page.wait_for_timeout(1500)
    rows = page.evaluate("""
    () => {
      const out = [];
      // selector amplio: cualquier <article> que contenga un precio €
      document.querySelectorAll('article').forEach(a => {
        const text = a.innerText || '';
        const linkEl = a.querySelector('a[href]');
        if (!linkEl) return;
        const url = new URL(linkEl.getAttribute('href'), location.origin).toString();
        const priceM = text.match(/([\\d.]+)\\s*€/);
        const yearM  = text.match(/\\b(19|20)\\d{2}\\b/);
        const kmM    = text.match(/([\\d.]+)\\s*km/i);
        const title  = (a.querySelector('h2, h3, [class*=title]')?.innerText || '').trim();
        const loc    = (a.querySelector('[class*=location], [class*=Location], [class*=city]')?.innerText || '').trim();
        if (!priceM) return;
        out.push({ url, title, raw_price: priceM[1], raw_year: yearM ? yearM[0] : null,
                   raw_km: kmM ? kmM[1] : null, raw_city: loc });
      });
      return out;
    }
    """)
    seen = set(); cleaned = []
    for r in rows:
        if r["url"] in seen: continue
        seen.add(r["url"])
        cleaned.append({
            "fuente": "coches.net",
            "id": r["url"].rsplit("/", 1)[-1].split("?")[0],
            "precio_eur": _to_int(r["raw_price"]),
            "anio": _to_int(r["raw_year"]),
            "km": _to_int(r["raw_km"]),
            "modelo": r["title"][:80],
            "combustible": "",
            "transmision": "",
            "ciudad": r["raw_city"][:60],
            "cp": "",
            "url": r["url"],
        })
    return cleaned

def scrape_wallapop(page):
    url = ("https://es.wallapop.com/app/search?keywords=toyota%20celica"
           "&latitude=40.4168&longitude=-3.7038&category_ids=100"
           "&min_year=2002&max_year=2006&distance=999000")
    print(f"  → {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.locator("button:has-text('Aceptar')").first.click(timeout=3000)
    except: pass
    try:
        page.wait_for_selector("a[href*='/item/'], tsl-item-card, .ItemCard", timeout=20000)
    except:
        print("  ! wallapop: no cargaron listings")
        return []
    page.wait_for_timeout(2000)
    # scroll para cargar más
    for _ in range(3):
        page.mouse.wheel(0, 4000); page.wait_for_timeout(800)
    rows = page.evaluate("""
    () => {
      const out = [];
      document.querySelectorAll("a[href*='/item/']").forEach(a => {
        const card = a.closest('tsl-item-card, .ItemCard, article, div') || a;
        const text = card.innerText || '';
        const priceM = text.match(/([\\d.]+)\\s*€/);
        const yearM  = text.match(/\\b(19|20)\\d{2}\\b/);
        const kmM    = text.match(/([\\d.]+)\\s*km/i);
        const title  = (card.querySelector('[class*=title], h2, h3')?.innerText || text.split('\\n')[0] || '').trim();
        const loc    = (card.querySelector('[class*=location], [class*=Location]')?.innerText || '').trim();
        if (!priceM) return;
        out.push({ url: a.href, title, raw_price: priceM[1],
                   raw_year: yearM ? yearM[0] : null, raw_km: kmM ? kmM[1] : null,
                   raw_city: loc });
      });
      return out;
    }
    """)
    seen = set(); cleaned = []
    for r in rows:
        if r["url"] in seen: continue
        seen.add(r["url"])
        title_low = (r["title"] or "").lower()
        # filtrado: tiene que ser celica
        if "celica" not in title_low and "celica" not in (r.get("raw_city","") or "").lower():
            # Fallback: a veces el card no incluye 'celica' en el primer texto pero sí en URL
            if "celica" not in r["url"].lower(): continue
        cleaned.append({
            "fuente": "wallapop",
            "id": r["url"].rstrip("/").rsplit("/", 1)[-1],
            "precio_eur": _to_int(r["raw_price"]),
            "anio": _to_int(r["raw_year"]),
            "km": _to_int(r["raw_km"]),
            "modelo": r["title"][:80],
            "combustible": "",
            "transmision": "",
            "ciudad": r["raw_city"][:60],
            "cp": "",
            "url": r["url"],
        })
    return cleaned

def main():
    today = datetime.date.today().isoformat()
    all_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-ES",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for name, fn in [("coches.net", scrape_coches), ("wallapop", scrape_wallapop)]:
            try:
                rows = fn(page)
                print(f"  ✓ {name}: {len(rows)} anuncios")
                all_rows.extend(rows)
            except Exception as e:
                print(f"  ✗ {name}: {e}")
        browser.close()

    if not all_rows:
        print("Sin datos nuevos (no escribo CSV).")
        return

    # de-duplicar contra lo ya escrito hoy en el CSV
    existing = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("fecha") == today:
                    existing.add((r["fuente"], r["id"]))
    fresh = [r for r in all_rows if (r["fuente"], r["id"]) not in existing]
    print(f"  → {len(fresh)} nuevos para añadir al CSV")

    fields = ["fecha","fuente","id","precio_eur","anio","km","modelo",
              "combustible","transmision","ciudad","cp","url"]
    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not file_exists: w.writeheader()
        for r in fresh:
            r["fecha"] = today
            w.writerow(r)
    print(f"Guardado en {CSV_PATH}")

if __name__ == "__main__":
    main()
