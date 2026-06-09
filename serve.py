#!/usr/bin/env python3
"""Sirve el dashboard y expone /api/scrape para refrescar desde el navegador.

GET  /                → dashboard.html
GET  /api/status      → estado del último/actual scrape + próximo auto-scrape
POST /api/scrape      → lanza scrape.py + scrape_playwright.py + build_dashboard.py
                        en background. 409 si ya hay uno corriendo.

Auto-scrape: un hilo en background relanza el scrape solo, a intervalos
aleatorios que promedian ~2h (pero pueden ser 10 min o 4h) y respetando unas
horas de silencio nocturnas, para parecer un usuario normal y no ser baneados.
Se controla con env vars:
  CELICA_AUTOSCRAPE=0   → desactiva el auto-scrape
  CELICA_QUIET_START/END → ventana sin scrapeo (por defecto 01:00–08:00)
"""
import http.server, socket, socketserver, json, os, subprocess, sys, threading, time
import datetime, random

import db

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("CELICA_PORT", "8765"))
BIND = os.environ.get("CELICA_BIND", "127.0.0.1")
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
SD_LISTEN_FDS_START = 3  # systemd socket activation

# --- Auto-scrape: intervalos (minutos) con pesos calibrados a media ~120 min ---
AUTO = os.environ.get("CELICA_AUTOSCRAPE", "1").lower() not in ("0", "false", "no", "")
INTERVALS_MIN    = [10, 20, 30, 45, 60, 90, 120, 150, 180, 210, 240]
INTERVAL_WEIGHTS = [ 1,  2,  3,  3,  4,  5,   6,   6,   5,   4,   3]
QUIET_START = int(os.environ.get("CELICA_QUIET_START", "1"))   # 01:00
QUIET_END   = int(os.environ.get("CELICA_QUIET_END", "8"))     # 08:00

state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "log": [],
    "ok": None,
    "auto": AUTO,
    "next_scrape_at": None,
    "auto_runs": 0,
    "last_trigger": None,
}
state_lock = threading.Lock()


def _append(line):
    with state_lock:
        state["log"].append(line)


def _last_csv_date():
    """Última fecha (ISO) registrada en el CSV, o None."""
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            dates = [ln.split(",", 1)[0] for ln in f if ln and not ln.startswith("fecha")]
        return max(dates) if dates else None
    except Exception:
        return None


def _pick_interval_min():
    """Un intervalo aleatorio en minutos: bucket ponderado + jitter ±15%."""
    base = random.choices(INTERVALS_MIN, weights=INTERVAL_WEIGHTS, k=1)[0]
    return base * random.uniform(0.85, 1.15)


def _in_quiet(hour):
    if QUIET_START <= QUIET_END:
        return QUIET_START <= hour < QUIET_END
    return hour >= QUIET_START or hour < QUIET_END  # ventana que cruza medianoche


def _next_run_ts(delay_min):
    """Timestamp objetivo dentro de `delay_min`; si cae en horas de silencio
    lo empuja al final de la ventana + un poco de jitter."""
    target = datetime.datetime.now() + datetime.timedelta(minutes=delay_min)
    if _in_quiet(target.hour):
        end = target.replace(hour=QUIET_END % 24, minute=0, second=0, microsecond=0)
        if end <= target:
            end += datetime.timedelta(days=1)
        end += datetime.timedelta(minutes=random.uniform(0, 50))
        target = end
    return target.timestamp()


def scheduler():
    """Relanza el scrape solo a intervalos humanos. Hilo daemon."""
    today = datetime.date.today().isoformat()
    # Primer scrape pronto si los datos no son de hoy; si no, intervalo normal.
    delay = random.uniform(2, 6) if _last_csv_date() != today else _pick_interval_min()
    while True:
        target_ts = _next_run_ts(delay)
        with state_lock:
            state["next_scrape_at"] = target_ts
        while time.time() < target_ts:
            time.sleep(min(60, max(1, target_ts - time.time())))
        with state_lock:
            busy = state["running"]
        if not busy:
            with state_lock:
                state["auto_runs"] += 1
            run_scrape(trigger="auto")
        delay = _pick_interval_min()


def run_scrape(trigger="manual"):
    with state_lock:
        state["running"] = True
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["log"] = []
        state["ok"] = None
        state["last_trigger"] = trigger
    _append(f"▶ scrape ({'automático' if trigger == 'auto' else 'manual'})")
    steps = [
        ("Autoscout24", ["python3", "scrape.py"]),
        ("Wallapop",    ["python3", "scrape_playwright.py"]),
        ("Dashboard",   ["python3", "build_dashboard.py"]),
    ]
    ok = True
    for name, cmd in steps:
        _append(f"▶ {name}…")
        try:
            proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=600)
            tail = (proc.stdout + proc.stderr).splitlines()[-25:]
            for ln in tail:
                _append("  " + ln)
            if proc.returncode == 0:
                _append(f"✓ {name} OK")
            else:
                _append(f"✗ {name} código {proc.returncode}")
                ok = False
        except subprocess.TimeoutExpired:
            _append(f"✗ {name} TIMEOUT (600s)")
            ok = False
        except Exception as e:
            _append(f"✗ {name} excepción: {e}")
            ok = False
    with state_lock:
        state["running"] = False
        state["finished_at"] = time.time()
        state["ok"] = ok


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", ""):
            self.path = "/dashboard.html"
        if self.path.startswith("/api/status"):
            with state_lock:
                self._json(200, dict(state))
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/scrape":
            with state_lock:
                if state["running"]:
                    self._json(409, {"error": "ya hay un scrape en marcha"})
                    return
            threading.Thread(target=run_scrape, daemon=True).start()
            self._json(202, {"started": True})
            return
        self.send_error(404)

    def end_headers(self):
        # dashboard.html cambia tras cada scrape: no cachear
        if self.path.endswith(".html") or self.path in ("/", ""):
            self.send_header("Cache-Control", "no-store")
        # CORS: permitir que la página abierta vía file:// pueda consultar el server
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        # Silencio: los logs HTTP no aportan
        pass


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _systemd_socket():
    """Si systemd nos pasó un socket vía socket activation, lo devuelve. Si no, None."""
    if os.environ.get("LISTEN_PID") and int(os.environ["LISTEN_PID"]) != os.getpid():
        return None
    n = int(os.environ.get("LISTEN_FDS", "0"))
    if n < 1:
        return None
    return socket.socket(fileno=SD_LISTEN_FDS_START)


def _init_db():
    """Inicializa la BD y auto-migra el CSV si está vacía (deploy transparente)."""
    try:
        conn = db.connect()
        db.init(conn)
        imported = db.maybe_import_csv(conn)
        if imported:
            print(f"BD auto-migrada desde CSV: {imported} filas", flush=True)
        print(f"BD lista: listings={db.count(conn,'listings')} "
              f"observations={db.count(conn,'observations')}", flush=True)
        conn.close()
    except Exception as e:
        print(f"⚠ No se pudo inicializar la BD: {e}", flush=True)


def main():
    os.chdir(HERE)
    _init_db()
    if AUTO:
        threading.Thread(target=scheduler, daemon=True).start()
        print("auto-scrape activado (media ~2h, silencio "
              f"{QUIET_START:02d}:00–{QUIET_END:02d}:00)", flush=True)
    sd_sock = _systemd_socket()
    if sd_sock is not None:
        httpd = ReusableServer((BIND, PORT), Handler, bind_and_activate=False)
        httpd.socket = sd_sock
        httpd.server_address = sd_sock.getsockname()
        print(f"celica-tracker (socket activation) ← fd {SD_LISTEN_FDS_START}", flush=True)
    else:
        httpd = ReusableServer((BIND, PORT), Handler)
        print(f"celica-tracker → http://{BIND}:{PORT}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
