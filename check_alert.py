#!/usr/bin/env python3
"""Ejecuta los scrapers, regenera el dashboard y compara la mediana de
precio del rango 2002-2006 entre la última recolección y la anterior.
Si el cambio es >=10%, lanza una notificación KDE (kdialog).
"""
import csv, datetime, os, statistics, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
LOG = os.path.join(HERE, "alert.log")
THRESHOLD = 0.10  # 10%

def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG, "a") as f: f.write(line + "\n")

def run(cmd):
    log(f"$ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=HERE,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log(r.stdout.decode("utf-8", "replace").rstrip())
    return r.returncode

def medians_by_date():
    """{fecha: mediana_2002_2006} ordenadas."""
    by_date = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: anio = int(r["anio"]) if r["anio"] else None
            except: anio = None
            try: precio = int(r["precio_eur"]) if r["precio_eur"] else None
            except: precio = None
            if anio and 2002 <= anio <= 2006 and precio and precio < 50000:
                by_date.setdefault(r["fecha"], []).append(precio)
    return [(d, statistics.median(by_date[d]), len(by_date[d]))
            for d in sorted(by_date)]

def best_value_picks(latest_date, n=3):
    """Top n anuncios del rango objetivo por mejor €/km."""
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["fecha"] != latest_date: continue
            try:
                anio = int(r["anio"]) if r["anio"] else None
                precio = int(r["precio_eur"]) if r["precio_eur"] else None
                km = int(r["km"]) if r["km"] else None
            except: continue
            if not (anio and precio and km): continue
            if 2002 <= anio <= 2006 and precio < 50000 and km > 1000:
                # heurística: precio bajo y km bajo
                rows.append((precio + km*0.05, r))
    rows.sort()
    return [r for _, r in rows[:n]]

def notify(title, body):
    """kdialog --passivepopup bloquea hasta cerrar/timeout, así que lo soltamos
    en su propia sesión y olvidamos."""
    try:
        subprocess.Popen(["kdialog", "--title", title, "--passivepopup", body, "30"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        log(f"Notificación enviada: {title}")
    except Exception as e:
        log(f"No se pudo notificar: {e}")

def main():
    log("=== check_alert ===")
    run("python3 scrape.py")
    run("python3 scrape_playwright.py")
    run("python3 build_dashboard.py")

    series = medians_by_date()
    if not series:
        log("Sin datos en el CSV.")
        return
    latest_date, latest_med, latest_n = series[-1]
    log(f"Última: {latest_date} mediana={latest_med:,.0f}€ n={latest_n}")

    if len(series) < 2:
        log("Sólo hay una recolección — sin comparativa todavía.")
        notify("🏎️ Celica · primera recolección",
               f"{latest_date}: {latest_n} anuncios 2002-2006, "
               f"mediana {latest_med:,.0f}€. Hace falta otra ejecución para comparar.")
        return
    prev_date, prev_med, prev_n = series[-2]
    delta = (latest_med - prev_med) / prev_med
    log(f"Anterior: {prev_date} mediana={prev_med:,.0f}€ n={prev_n} → Δ={delta:+.1%}")

    picks = best_value_picks(latest_date, 3)
    picks_txt = "\n".join(
        f"• {p['anio']} · {int(p['precio_eur']):,}€ · {int(p['km'])//1000}k km · {(p['ciudad'] or '?')[:30]}"
        for p in picks)

    arrow = "🔺" if delta > 0 else "🔻"
    if abs(delta) >= THRESHOLD:
        notify(f"🏎️ Celica {arrow} {delta:+.0%}",
               f"Mediana 2002-2006: {prev_med:,.0f}€ → {latest_med:,.0f}€\n"
               f"({prev_date} → {latest_date}, n={latest_n})\n\n"
               f"Top picks (€/km):\n{picks_txt}")
    else:
        log(f"Cambio {delta:+.1%} bajo umbral {THRESHOLD:.0%} — sin alerta.")
        # notificación silenciosa (informativa) cada lunes igualmente
        notify(f"🏎️ Celica · semanal {delta:+.1%}",
               f"Mediana 2002-2006: {latest_med:,.0f}€ ({latest_n} anuncios)\n"
               f"Cambio vs {prev_date}: {delta:+.1%} (sin alerta).\n\n"
               f"Top picks:\n{picks_txt}")

if __name__ == "__main__":
    main()
