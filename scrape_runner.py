#!/usr/bin/env python3
"""Motor de scraping del celica-tracker: ejecución manual + auto-scrape.

Extraído de serve.py para poder lanzarlo desde FastAPI (app.py). El estado vive
en memoria del proceso, protegido por un lock. El auto-scrape es un hilo daemon
del servidor (no depende de ningún usuario); el scrape manual lo dispara el
endpoint /api/scrape, que en app.py exige rol admin.

Env vars:
  CELICA_AUTOSCRAPE=0      → desactiva el auto-scrape
  CELICA_QUIET_START/END   → ventana nocturna sin scrapeo (def 01:00–08:00)
"""
import datetime
import os
import random
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")

AUTO = os.environ.get("CELICA_AUTOSCRAPE", "1").lower() not in ("0", "false", "no", "")
INTERVALS_MIN    = [10, 20, 30, 45, 60, 90, 120, 150, 180, 210, 240]
INTERVAL_WEIGHTS = [ 1,  2,  3,  3,  4,  5,   6,   6,   5,   4,   3]
QUIET_START = int(os.environ.get("CELICA_QUIET_START", "1"))
QUIET_END   = int(os.environ.get("CELICA_QUIET_END", "8"))

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


def snapshot():
    with state_lock:
        return dict(state)


def is_running():
    with state_lock:
        return state["running"]


def _append(line):
    with state_lock:
        state["log"].append(line)


def _last_csv_date():
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            dates = [ln.split(",", 1)[0] for ln in f if ln and not ln.startswith("fecha")]
        return max(dates) if dates else None
    except Exception:
        return None


def _pick_interval_min():
    base = random.choices(INTERVALS_MIN, weights=INTERVAL_WEIGHTS, k=1)[0]
    return base * random.uniform(0.85, 1.15)


def _in_quiet(hour):
    if QUIET_START <= QUIET_END:
        return QUIET_START <= hour < QUIET_END
    return hour >= QUIET_START or hour < QUIET_END


def _next_run_ts(delay_min):
    target = datetime.datetime.now() + datetime.timedelta(minutes=delay_min)
    if _in_quiet(target.hour):
        end = target.replace(hour=QUIET_END % 24, minute=0, second=0, microsecond=0)
        if end <= target:
            end += datetime.timedelta(days=1)
        end += datetime.timedelta(minutes=random.uniform(0, 50))
        target = end
    return target.timestamp()


def run_scrape(trigger="manual"):
    """Ejecuta los 3 pasos (autoscout, wallapop, dashboard) en serie. Bloqueante.
    No relanza si ya hay uno corriendo."""
    with state_lock:
        if state["running"]:
            return False
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
    return True


def start_scrape_async(trigger="manual"):
    """Lanza un scrape en background si no hay otro en marcha. True si arrancó."""
    with state_lock:
        if state["running"]:
            return False
    threading.Thread(target=run_scrape, args=(trigger,), daemon=True).start()
    return True


def _scheduler():
    today = datetime.date.today().isoformat()
    delay = random.uniform(2, 6) if _last_csv_date() != today else _pick_interval_min()
    while True:
        target_ts = _next_run_ts(delay)
        with state_lock:
            state["next_scrape_at"] = target_ts
        while time.time() < target_ts:
            time.sleep(min(60, max(1, target_ts - time.time())))
        if not is_running():
            with state_lock:
                state["auto_runs"] += 1
            run_scrape(trigger="auto")
        delay = _pick_interval_min()


def start_scheduler():
    """Arranca el hilo daemon de auto-scrape si CELICA_AUTOSCRAPE está activo."""
    if not AUTO:
        return False
    threading.Thread(target=_scheduler, daemon=True).start()
    return True
