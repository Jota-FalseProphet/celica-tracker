# celica-tracker

Mini-pipeline para seguir el mercado de Toyota Celica en España (foco: 2002-2006, generación T230) y detectar movimientos de precio.

Scrapea Autoscout24 y Wallapop, guarda el histórico en **PostgreSQL** (con `celica_prices.csv` como export de backup legible), genera un **dashboard web interactivo** (tema claro/oscuro, gráficas con zoom, fotos de cada coche, favoritos, buscador/filtros, figuras 3D) y avisa por `kdialog` si la mediana se mueve ≥ 10% semana a semana.

## Stack

- Python 3 + `requests` para Autoscout24 (lee `__NEXT_DATA__` del SSR).
- Playwright (Chromium headless) para Wallapop.
- **PostgreSQL** como fuente de verdad (`db.py`, psycopg 3). Modela el ciclo de
  vida de cada anuncio (`listings` + `observations`) → nuevos, bajadas de precio,
  días en venta y chollos salen gratis.
- Frontend: Chart.js + `chartjs-plugin-zoom`, **three.js** (figuras 3D cromadas
  vía WebGL), fuentes Saira + JetBrains Mono. Tema claro/oscuro, estilo copiado
  del portfolio (cielo frutiger/PS2, paneles glass, iconos SVG).
- `serve.py` con **auto-scrape**: relanza el scrape solo a intervalos aleatorios
  que promedian ~2h (con jitter y horas de silencio) para parecer un usuario real.

## Instalación

```bash
pip install requests playwright "psycopg[binary]"
playwright install chromium
# y un Postgres accesible vía CELICA_DATABASE_URL (ver docker-compose.yml)
export CELICA_DATABASE_URL=postgresql://celica:celica@localhost:5432/celica
python3 migrate.py   # importa celica_prices.csv a la BD (idempotente)
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
| `db.py` | Capa de datos Postgres (esquema, UPSERT idempotente, export/import CSV) |
| `migrate.py` | Importa `celica_prices.csv` → BD (idempotente; el arranque ya lo hace solo) |
| `scrape.py` | Scraper de Autoscout24 → BD |
| `scrape_playwright.py` | Scraper de Wallapop → BD |
| `build_dashboard.py` | Genera `dashboard.html` desde la BD y exporta el CSV de backup |
| `scene.js` + `three.module.js` | Figuras 3D cromadas (WebGL). Fallback sin WebGL: sin figuras |
| `check_alert.py` | Compara la mediana actual vs. la anterior y dispara `kdialog` |
| `serve.py` | HTTP server (`/api/scrape`, `/api/status`) + auto-scrape en background |
| `graph.py` | Genera `celica_market.png` (gráfico estático PNG) |
| `refresh_and_open.sh` | Script "todo en uno" |
| `Dockerfile` · `docker-compose.yml` | Imagen del scraper + stack (celica + Postgres) |
| `celica_prices.csv` | Export de backup (git): `fecha, fuente, id, precio_eur, anio, km, modelo, combustible, transmision, ciudad, cp, url, foto` |
| `TODO.md` | Roadmap multiusuario (roles, admin único que puede refrescar) |

## Base de datos

Postgres es la fuente de verdad. Dos tablas:

- `listings` — un anuncio único (`key = fuente:id`) con metadatos y `first_seen` / `last_seen`.
- `observations` — precio/km por anuncio y día. PK `(key, fecha)` ⇒ re-scrapear el
  mismo día es **idempotente** (UPSERT), sin duplicados.

`build_dashboard.py` exporta todo a `celica_prices.csv` tras cada generación, así
que el histórico sigue siendo visible en los diffs de git.

## Auto-scrape

`serve.py` lanza un hilo que relanza el scrape solo. El intervalo es aleatorio
(buckets ponderados 10 min–4 h, media ~2 h, +jitter ±15%) y respeta una ventana de
silencio nocturna (por defecto 01:00–08:00) para no parecer un bot. Configurable:

```
CELICA_AUTOSCRAPE=0          # desactivar
CELICA_QUIET_START=1         # inicio ventana de silencio (hora)
CELICA_QUIET_END=8           # fin ventana de silencio (hora)
```

`/api/status` expone `next_scrape_at` y el dashboard muestra el próximo auto-scrape.

## Dashboard (UI)

- **Dos pestañas**: *Listado* (tarjetas con foto del coche, precio, año, km, días
  en venta) y *Gráficas*.
- **Señales de compra** por anuncio: `NUEVO` (visto hoy por primera vez),
  `OPORTUNIDAD` (precio ≤ 85% del esperado según ajuste precio~km) y
  `↓ -X%` (bajada respecto a la observación previa).
- **Favoritos** ⭐ por coche (persisten en `localStorage`), **buscador**, **orden**
  y **filtros** (fuente, solo oportunidades, solo favoritos). Los recuadros de
  estadísticas de arriba son clicables (aplican el filtro/orden correspondiente).
- **Gráficas** (Chart.js): precio vs km, histórico con banda intercuartil,
  distribución de precios y mediana por año. Zoom arrastrando para seleccionar un
  rango, botón para reiniciar y ampliar a pantalla completa.
- **Tema claro/oscuro** con transición de wipe radial (View Transitions), cielo +
  nubes + grano de fondo y **figuras 3D cromadas** (three.js).

## Docker / deploy

```bash
docker compose up -d --build     # levanta Postgres + celica; auto-migra el CSV
docker compose logs -f celica
```

El servicio `db` (Postgres) vive en una red interna aislada (`celica_internal`);
solo `celica` lo ve. `celica` también está en `sefer_default` para que lo alcancen
sefer-nginx / Cloudflare Tunnel. Define `CELICA_DB_PASSWORD` en un `.env` para no
usar la contraseña por defecto.

## Aviso semanal (systemd user, escritorio)

Camino opcional de **escritorio** (independiente del auto-scrape del contenedor):
`check_alert.py` scrapea, compara la mediana y avisa con `kdialog`. Configurado con
un `.timer` (`OnCalendar=Mon 09:00`, `Persistent=true`). Usa systemd user en lugar
de cron porque cron no hereda el bus DBUS de la sesión KDE y `kdialog` no
encontraría dónde pintar. (En el deploy del contenedor no aplica: el aviso es por
`kdialog`, que necesita sesión gráfica.)

```bash
systemctl --user list-timers celica-check.timer
systemctl --user start celica-check.service     # ejecutar ahora
journalctl --user -u celica-check.service       # logs
```

## Server del dashboard

`serve.py` escucha en `:8765` (en el contenedor `0.0.0.0`). Sirve `dashboard.html`,
expone `/api/scrape` (refrescar a mano) y `/api/status` (estado + próximo
auto-scrape), y corre el hilo de auto-scrape. En el deploy lo levanta docker
compose con `restart: unless-stopped`.

## Fuentes

- **Autoscout24** — único portal grande con SSR utilizable. 1 GET con `requests`, parsear `__NEXT_DATA__`.
- **Wallapop** — SPA con API que devuelve 403/404 sin auth. Playwright headless.
- **Coches.net** — *no funciona*. DataDome bloquea Chromium/Firefox incluso con stealth y warmup. Necesita proxy residencial o servicio anti-DataDome.

## Limitaciones

- El mercado es pequeño (~25 Celicas T230 entre los dos portales en un día), así que un único anuncio mueve la mediana mucho.
- La tendencia temporal sólo es útil tras 2-3 semanas de recolección.
- El dashboard descarta precios > 50.000 € (rally / Carlos Sainz / show car).
