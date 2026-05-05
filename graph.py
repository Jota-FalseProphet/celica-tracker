#!/usr/bin/env python3
"""Genera un PNG con la situación de precios. Ejecutar tras scrape.py.
- Panel 1: precio vs km, todas las Celicas ES, T230 (2000-2006) destacado y
  rango objetivo 2002-2006 marcado.
- Panel 2: evolución temporal (mediana del rango 2002-2006 a lo largo de
  las recolecciones acumuladas).
"""
import csv, datetime, os, statistics, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
OUT_PATH = os.path.join(HERE, "celica_market.png")

def load():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["precio_eur"] = int(r["precio_eur"]) if r["precio_eur"] else None
                r["anio"] = int(r["anio"]) if r["anio"] else None
                r["km"] = int(r["km"]) if r["km"] else None
            except: continue
            rows.append(r)
    return rows

def main():
    rows = load()
    if not rows:
        print("Sin datos. Ejecuta scrape.py primero.")
        return
    # Filtros — descartamos outliers extremos (rally / 1km / >100k €)
    clean = [r for r in rows if r["precio_eur"] and r["km"] and r["anio"]
             and r["precio_eur"] < 50000 and r["km"] > 1000]

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6),
                                   gridspec_kw={"width_ratios": [1.4, 1]})

    target = [r for r in clean if 2002 <= r["anio"] <= 2006]
    t230   = [r for r in clean if 2000 <= r["anio"] <= 2006 and not (2002 <= r["anio"] <= 2006)]
    other  = [r for r in clean if not (2000 <= r["anio"] <= 2006)]

    if other:
        ax1.scatter([r["km"]/1000 for r in other], [r["precio_eur"] for r in other],
                    c="#666", s=60, alpha=0.6, label=f"Otras Celica ({len(other)})", edgecolors="none")
    if t230:
        ax1.scatter([r["km"]/1000 for r in t230], [r["precio_eur"] for r in t230],
                    c="#4a9eff", s=90, alpha=0.85, label=f"T230 fuera del rango ({len(t230)})", edgecolors="white", linewidths=0.5)
    if target:
        ax1.scatter([r["km"]/1000 for r in target], [r["precio_eur"] for r in target],
                    c="#ff5252", s=160, alpha=0.95, label=f"2002-2006 OBJETIVO ({len(target)})",
                    edgecolors="white", linewidths=1.2, marker="*")
        # anota cada uno
        for r in target:
            ax1.annotate(f'{r["anio"]} · {r["precio_eur"]:,}€\n{r["ciudad"] or ""}',
                         (r["km"]/1000, r["precio_eur"]),
                         textcoords="offset points", xytext=(10,10),
                         fontsize=9, color="#ffcccc")

    ax1.set_xlabel("Kilómetros (miles)")
    ax1.set_ylabel("Precio (€)")
    ax1.set_title(f"Toyota Celica en venta en España — {datetime.date.today().isoformat()}\nfuente: Autoscout24",
                  fontsize=12)
    ax1.grid(alpha=0.2)
    ax1.legend(loc="upper right", framealpha=0.3)

    # Panel 2: histograma del rango objetivo + estadísticas
    if target:
        prices = [r["precio_eur"] for r in target]
        ax2.barh([f'{r["anio"]} · {r["modelo"]}\n{(r["ciudad"] or "?")} · {r["km"]//1000}k km'
                  for r in sorted(target, key=lambda x:x["precio_eur"])],
                 sorted(prices),
                 color="#ff5252", alpha=0.85, edgecolor="white")
        ax2.set_xlabel("Precio (€)")
        ax2.set_title(f"Rango objetivo 2002-2006\nmediana: {int(statistics.median(prices)):,}€  ·  "
                      f"min: {min(prices):,}€  ·  max: {max(prices):,}€",
                      fontsize=12)
        ax2.grid(alpha=0.2, axis="x")
        for i, p in enumerate(sorted(prices)):
            ax2.text(p, i, f"  {p:,}€", va="center", fontsize=10, color="white")
    else:
        ax2.text(0.5, 0.5, "Sin anuncios en\nrango objetivo", ha="center", va="center",
                 transform=ax2.transAxes, fontsize=14)

    # Panel 2-extra: nota de tendencia si hay datos históricos
    fechas = sorted({r["fecha"] for r in rows})
    if len(fechas) > 1:
        # mediana del rango objetivo por fecha
        per_date = collections.defaultdict(list)
        for r in rows:
            if r["anio"] and 2002 <= r["anio"] <= 2006 and r["precio_eur"]:
                per_date[r["fecha"]].append(r["precio_eur"])
        if len(per_date) > 1:
            xs = sorted(per_date)
            ys = [statistics.median(per_date[d]) for d in xs]
            inset = fig.add_axes([0.62, 0.18, 0.33, 0.18])
            inset.plot(xs, ys, "o-", color="#ffcc00")
            inset.set_title("Mediana 2002-2006 vs tiempo", fontsize=9)
            inset.tick_params(labelsize=8)
            inset.grid(alpha=0.2)

    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=120, bbox_inches="tight", facecolor="#1a1a1a")
    print(f"Gráfica → {OUT_PATH}")

if __name__ == "__main__":
    main()
