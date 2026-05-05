#!/usr/bin/env python3
"""Sirve el dashboard y expone /api/scrape para refrescar desde el navegador.

GET  /                → dashboard.html
GET  /api/status      → estado del último/actual scrape
POST /api/scrape      → lanza scrape.py + scrape_playwright.py + build_dashboard.py
                        en background. 409 si ya hay uno corriendo.
"""
import http.server, socket, socketserver, json, os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("CELICA_PORT", "8765"))
SD_LISTEN_FDS_START = 3  # systemd socket activation

state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "log": [],
    "ok": None,
}
state_lock = threading.Lock()


def _append(line):
    with state_lock:
        state["log"].append(line)


def run_scrape():
    with state_lock:
        state["running"] = True
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["log"] = []
        state["ok"] = None
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
        if self.path == "/api/shutdown":
            with state_lock:
                if state["running"]:
                    self._json(409, {"error": "scrape en marcha, espera o cancela"})
                    return
            self._json(202, {"stopping": True})
            # Apagado diferido para que la respuesta llegue al cliente
            threading.Thread(target=lambda: (time.sleep(0.3), self.server.shutdown()),
                             daemon=True).start()
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


def main():
    os.chdir(HERE)
    sd_sock = _systemd_socket()
    if sd_sock is not None:
        httpd = ReusableServer(("127.0.0.1", PORT), Handler, bind_and_activate=False)
        httpd.socket = sd_sock
        httpd.server_address = sd_sock.getsockname()
        print(f"celica-tracker (socket activation) ← fd {SD_LISTEN_FDS_START}", flush=True)
    else:
        httpd = ReusableServer(("127.0.0.1", PORT), Handler)
        print(f"celica-tracker → http://127.0.0.1:{PORT}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
