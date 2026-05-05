# celica-tracker

Mini-pipeline para seguir el mercado de Toyota Celica en España (foco: 2002-2006, generación T230) y detectar movimientos de precio.

Scrapea Autoscout24 y Wallapop, guarda un histórico append-only en CSV, genera un dashboard estático y avisa por `kdialog` si la mediana se mueve ≥ 10% semana a semana.

## Stack

- Python 3 + `requests` para Autoscout24 (lee `__NEXT_DATA__` del SSR).
- Playwright (Chromium headless) para Wallapop.
- Chart.js (CDN) en el dashboard.
- systemd user units para programar el aviso semanal y servir el dashboard con socket activation.

## Instalación

```bash
pip install requests playwright
playwright install chromium
```

## Uso

```bash
python3 scrape.py             # Autoscout24
python3 scrape_playwright.py  # Wallapop
python3 build_dashboard.py    # genera dashboard.html
```

`refresh_and_open.sh` hace los tres pasos y abre el dashboard en el navegador.

## Archivos

| Archivo | Qué hace |
|---|---|
| `scrape.py` | Scraper de Autoscout24 |
| `scrape_playwright.py` | Scraper de Wallapop |
| `build_dashboard.py` | Genera `dashboard.html` desde el CSV |
| `check_alert.py` | Compara la mediana actual vs. la anterior y dispara `kdialog` |
| `serve.py` | HTTP server con endpoints `/api/scrape`, `/api/status`, `/api/shutdown` |
| `graph.py` | Genera `celica_market.png` (gráfico estático) |
| `refresh_and_open.sh` | Script "todo en uno" |
| `celica_prices.csv` | Histórico append-only: `fecha, fuente, id, precio_eur, anio, km, modelo, combustible, transmision, ciudad, cp, url` |

## Aviso semanal (systemd user)

Configurado con un `.timer` (`OnCalendar=Mon 09:00`, `Persistent=true`). Usa systemd user en lugar de cron porque cron no hereda el bus DBUS de la sesión KDE y `kdialog` no encontraría dónde pintar.

```bash
systemctl --user list-timers celica-check.timer
systemctl --user start celica-check.service     # ejecutar ahora
journalctl --user -u celica-check.service       # logs
```

## Server del dashboard (socket activation)

`serve.py` escucha en `127.0.0.1:8765`. No se arranca a mano: hay un `.socket` systemd que lo despierta al primer request y lo deja apagado el resto del tiempo.

```bash
systemctl --user enable --now celica-tracker.socket
```

El botón "▶ Arrancar server" del dashboard hace `fetch` al puerto y systemd levanta el servicio.

## Fuentes

- **Autoscout24** — único portal grande con SSR utilizable. 1 GET con `requests`, parsear `__NEXT_DATA__`.
- **Wallapop** — SPA con API que devuelve 403/404 sin auth. Playwright headless.
- **Coches.net** — *no funciona*. DataDome bloquea Chromium/Firefox incluso con stealth y warmup. Necesita proxy residencial o servicio anti-DataDome.

## Limitaciones

- El mercado es pequeño (~25 Celicas T230 entre los dos portales en un día), así que un único anuncio mueve la mediana mucho.
- La tendencia temporal sólo es útil tras 2-3 semanas de recolección.
- El dashboard descarta precios > 50.000 € (rally / Carlos Sainz / show car).
