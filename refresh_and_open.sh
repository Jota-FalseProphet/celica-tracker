#!/usr/bin/env bash
# Refresca los datos (si hay red), arranca serve.py si no estaba, y abre el dashboard.
set -u
cd "$(dirname "$0")"
LOG="$(pwd)/last_run.log"
PORT="${CELICA_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"

{
  echo "=== $(date -Iseconds) ==="
  # Espera a que haya red (hasta 60s)
  for i in $(seq 1 12); do
    if curl -s --max-time 3 -o /dev/null https://www.autoscout24.es/; then
      echo "red OK tras ${i} intentos"
      break
    fi
    sleep 5
  done
  python3 scrape.py || echo "scrape Autoscout24 falló"
  python3 scrape_playwright.py || echo "scrape Playwright (Wallapop) falló"
  python3 build_dashboard.py || echo "build_dashboard falló"
} >> "$LOG" 2>&1

# Arranca serve.py en background si el puerto no está escuchando
if ! curl -s --max-time 1 -o /dev/null "${URL}api/status"; then
  echo "Arrancando serve.py en :${PORT}" >> "$LOG"
  nohup python3 serve.py >> "$LOG" 2>&1 &
  disown || true
  # Espera a que el server esté listo (hasta 5s)
  for i in $(seq 1 10); do
    curl -s --max-time 1 -o /dev/null "${URL}api/status" && break
    sleep 0.5
  done
fi

xdg-open "$URL" >/dev/null 2>&1 &
