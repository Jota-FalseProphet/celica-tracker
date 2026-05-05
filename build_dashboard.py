#!/usr/bin/env python3
"""Genera dashboard.html con los datos de celica_prices.csv."""
import csv, datetime, json, os, statistics, html

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
HTML_PATH = os.path.join(HERE, "dashboard.html")

def load():
    out = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["precio_eur"] = int(r["precio_eur"]) if r["precio_eur"] else None
                r["anio"] = int(r["anio"]) if r["anio"] else None
                r["km"] = int(r["km"]) if r["km"] else None
            except: continue
            out.append(r)
    return out

def main():
    rows = load()
    today = max((r["fecha"] for r in rows), default=datetime.date.today().isoformat())
    latest = [r for r in rows if r["fecha"] == today]
    target = sorted([r for r in latest if r["anio"] and 2002 <= r["anio"] <= 2006],
                    key=lambda x: x["precio_eur"] or 0)
    t230 = sorted([r for r in latest if r["anio"] and 2000 <= r["anio"] <= 2006
                   and not (2002 <= r["anio"] <= 2006)],
                  key=lambda x: x["precio_eur"] or 0)
    other = sorted([r for r in latest if not (r["anio"] and 2000 <= r["anio"] <= 2006)
                    and r["precio_eur"] and r["precio_eur"] < 50000],
                   key=lambda x: x["precio_eur"] or 0)
    target_prices = [r["precio_eur"] for r in target if r["precio_eur"]]

    stats_html = ""
    if target_prices:
        stats_html = f"""
        <div class="stat"><span class="num">{len(target)}</span><span class="lbl">anuncios 2002-2006</span></div>
        <div class="stat"><span class="num">{min(target_prices):,}€</span><span class="lbl">más barato</span></div>
        <div class="stat"><span class="num">{int(statistics.median(target_prices)):,}€</span><span class="lbl">mediana</span></div>
        <div class="stat"><span class="num">{max(target_prices):,}€</span><span class="lbl">más caro</span></div>
        """.replace(",", ".")

    def card(r, klass=""):
        precio = f'{r["precio_eur"]:,}€'.replace(",", ".") if r["precio_eur"] else "?"
        km = f'{r["km"]//1000}k km' if r["km"] else "? km"
        ciudad = (r["ciudad"] or "").strip() or "?"
        return f"""<a class="card {klass}" href="{html.escape(r['url'])}" target="_blank">
            <div class="price">{precio}<span class="src src-{r['fuente'].split('.')[0]}">{html.escape(r['fuente'])}</span></div>
            <div class="meta">
                <span class="year">{r['anio'] or '?'}</span> ·
                <span>{html.escape((r['modelo'] or '').strip())}</span>
            </div>
            <div class="sub">{html.escape(ciudad)} · {km} · {html.escape(r['combustible'] or '')}</div>
        </a>"""

    # contar por fuente
    by_src = {}
    for r in latest:
        by_src[r["fuente"]] = by_src.get(r["fuente"], 0) + 1
    src_summary = " · ".join(f'{k}: {v}' for k,v in sorted(by_src.items()))

    # series temporal por fecha (mediana del rango 2002-2006)
    by_date = {}
    for r in rows:
        if r["anio"] and 2002 <= r["anio"] <= 2006 and r["precio_eur"]:
            by_date.setdefault(r["fecha"], []).append(r["precio_eur"])
    history = [{"fecha": d, "mediana": statistics.median(by_date[d]),
                "min": min(by_date[d]), "max": max(by_date[d]), "n": len(by_date[d])}
               for d in sorted(by_date)]

    scatter_data = {
        "target": [{"km": r["km"], "precio": r["precio_eur"], "anio": r["anio"],
                    "modelo": r["modelo"], "ciudad": r["ciudad"], "url": r["url"]}
                   for r in target if r["km"] and r["precio_eur"]],
        "t230": [{"km": r["km"], "precio": r["precio_eur"], "anio": r["anio"],
                  "modelo": r["modelo"], "ciudad": r["ciudad"], "url": r["url"]}
                 for r in t230 if r["km"] and r["precio_eur"]],
        "other": [{"km": r["km"], "precio": r["precio_eur"], "anio": r["anio"],
                   "modelo": r["modelo"], "ciudad": r["ciudad"], "url": r["url"]}
                  for r in other if r["km"] and r["precio_eur"]],
    }

    HTML = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Toyota Celica · mercado España</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, system-ui, sans-serif;
         background: #0f0f12; color: #eee; padding: 24px; max-width: 1280px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 28px; }}
  .sub {{ color: #888; margin-bottom: 24px; font-size: 14px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: #1a1a20; border-radius: 12px; padding: 16px 20px; flex: 1; min-width: 140px;
          border: 1px solid #2a2a32; }}
  .stat .num {{ display: block; font-size: 28px; font-weight: 700; color: #ff5252; }}
  .stat .lbl {{ display: block; font-size: 12px; color: #888; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .grid {{ display: grid; grid-template-columns: 1.5fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .panel {{ background: #1a1a20; border-radius: 12px; padding: 20px; border: 1px solid #2a2a32; }}
  .panel h2 {{ margin: 0 0 16px; font-size: 16px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; }}
  canvas {{ max-height: 360px; }}
  section h2 {{ font-size: 14px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin: 32px 0 12px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }}
  .card {{ background: #1a1a20; border: 1px solid #2a2a32; border-radius: 10px; padding: 14px;
          text-decoration: none; color: inherit; transition: all 0.15s;
          display: block; }}
  .card:hover {{ transform: translateY(-2px); border-color: #ff5252; background: #1f1a1a; }}
  .card.target {{ border-color: #ff5252; background: linear-gradient(135deg, #2a1a1a, #1a1a20); }}
  .card.t230 {{ border-color: #4a9eff44; }}
  .card .price {{ font-size: 22px; font-weight: 700; color: #ff5252; }}
  .card.t230 .price {{ color: #4a9eff; }}
  .card.other .price {{ color: #aaa; }}
  .card .meta {{ font-size: 14px; margin: 6px 0 4px; color: #ddd; }}
  .card .meta .year {{ background: #ff525222; padding: 2px 8px; border-radius: 4px; font-weight: 600; }}
  .card.t230 .meta .year {{ background: #4a9eff22; }}
  .card.other .meta .year {{ background: #ffffff11; }}
  .card .sub {{ font-size: 12px; color: #888; margin: 0; }}
  .src {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 8px; vertical-align: middle; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}
  .src-autoscout24 {{ background: #ffcc00; color: #000; }}
  .src-wallapop {{ background: #00d4ff; color: #000; }}
  .src-coches {{ background: #f44; color: #fff; }}
  .toolbar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .refresh-btn {{ background: linear-gradient(135deg, #ff5252, #ff7752); color: #fff; border: 0;
                 padding: 12px 22px; border-radius: 10px; cursor: pointer; font-weight: 700;
                 font-size: 14px; letter-spacing: 0.3px; transition: all 0.15s;
                 box-shadow: 0 4px 14px #ff525233; }}
  .refresh-btn:hover:not(:disabled) {{ transform: translateY(-1px); box-shadow: 0 6px 20px #ff525266; }}
  .refresh-btn:disabled {{ background: #444; cursor: wait; box-shadow: none; opacity: 0.7; }}
  .refresh-btn .spin {{ display: inline-block; animation: spin 1s linear infinite; }}
  .ghost-btn {{ background: #2a2a32; color: #ddd; border: 1px solid #3a3a44;
               padding: 12px 18px; border-radius: 10px; cursor: pointer; font-weight: 600;
               font-size: 13px; transition: all 0.15s; }}
  .ghost-btn:hover:not(:disabled) {{ background: #1f2a1f; border-color: #4ade80; color: #4ade80; }}
  .ghost-btn.danger:hover:not(:disabled) {{ background: #3a2a2a; border-color: #ff5252; color: #ff7777; }}
  .ghost-btn:disabled {{ opacity: 0.35; cursor: not-allowed; }}
  .modal-bg {{ position: fixed; inset: 0; background: #000a; display: none; align-items: center;
              justify-content: center; z-index: 100; }}
  .modal-bg.active {{ display: flex; }}
  .modal {{ background: #14141a; border: 1px solid #2a2a32; border-radius: 12px; padding: 22px;
           max-width: 480px; width: calc(100% - 40px); box-shadow: 0 12px 40px #000c; }}
  .modal h3 {{ margin: 0 0 8px; font-size: 16px; }}
  .modal p {{ margin: 0 0 14px; color: #aaa; font-size: 13px; line-height: 1.5; }}
  .modal code {{ display: block; background: #0a0a0d; border: 1px solid #2a2a32; padding: 10px 14px;
                border-radius: 8px; font-family: ui-monospace, Menlo, monospace; font-size: 13px;
                color: #ffcc00; margin-bottom: 12px; word-break: break-all; }}
  .modal .row {{ display: flex; gap: 8px; justify-content: flex-end; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .refresh-hint {{ color: #777; font-size: 12px; }}
  .logs-panel {{ position: fixed; top: 16px; right: 16px; width: 380px; max-height: calc(100vh - 32px);
                background: #0a0a0d; border: 1px solid #2a2a32; border-radius: 12px;
                box-shadow: 0 8px 32px #000a; display: none; flex-direction: column;
                z-index: 50; overflow: hidden; }}
  .logs-panel.active {{ display: flex; }}
  .logs-head {{ display: flex; align-items: center; justify-content: space-between;
               padding: 10px 14px; border-bottom: 1px solid #2a2a32; background: #14141a; }}
  .logs-head .title {{ font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
  .logs-head .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                    background: #555; margin-right: 8px; vertical-align: middle; }}
  .logs-head .dot.live {{ background: #4ade80; box-shadow: 0 0 8px #4ade80; animation: pulse 1.2s ease-in-out infinite; }}
  .logs-head .dot.ok   {{ background: #4ade80; }}
  .logs-head .dot.err  {{ background: #ff5252; }}
  @keyframes pulse {{ 50% {{ opacity: 0.4; }} }}
  .logs-head .close {{ background: none; border: 0; color: #888; font-size: 18px; cursor: pointer; padding: 0 4px; }}
  .logs-head .close:hover {{ color: #fff; }}
  .refresh-log {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #bbb;
                 padding: 12px 14px; overflow-y: auto; white-space: pre-wrap; line-height: 1.5;
                 flex: 1; min-height: 80px; }}
  @media (max-width: 1100px) {{
    .logs-panel {{ position: static; width: auto; max-height: 280px; margin-bottom: 20px;
                  box-shadow: none; }}
  }}
  footer {{ margin-top: 40px; color: #555; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<h1>🏎️ Toyota Celica · mercado España</h1>
<div class="sub">Última actualización: {today} · {len(latest)} anuncios · {src_summary}</div>

<div class="toolbar">
  <button id="refresh-btn" class="refresh-btn" onclick="doRefresh()">↻ Refrescar ahora</button>
  <button id="power-btn" class="ghost-btn" onclick="doPower()">⏻ Apagar server</button>
  <span id="refresh-hint" class="refresh-hint"></span>
</div>
<div id="modal-bg" class="modal-bg" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <h3>Arrancar el server</h3>
    <p>El navegador no puede lanzar procesos. Ejecuta esto en una terminal y se abrirá automáticamente cuando esté listo:</p>
    <code id="modal-cmd">python3 /home/jota/cosasJota/celica-tracker/serve.py</code>
    <div class="row">
      <button class="ghost-btn" onclick="copyCmd(event)">📋 Copiar</button>
      <button class="ghost-btn" onclick="closeModal()">Cerrar</button>
    </div>
  </div>
</div>
<aside id="logs-panel" class="logs-panel">
  <div class="logs-head">
    <span><span id="logs-dot" class="dot"></span><span id="logs-title" class="title">Logs</span></span>
    <button class="close" onclick="document.getElementById('logs-panel').classList.remove('active')" title="Cerrar">×</button>
  </div>
  <div id="refresh-log" class="refresh-log"></div>
</aside>

<div class="stats">{stats_html}</div>

<div class="grid">
  <div class="panel"><h2>Precio vs kilómetros</h2><canvas id="scatter"></canvas></div>
  <div class="panel"><h2>Histórico mediana 2002-2006</h2><canvas id="history"></canvas></div>
</div>

<section>
<h2>🎯 Rango objetivo 2002-2006 ({len(target)})</h2>
<div class="cards">{''.join(card(r, 'target') for r in target) or '<p style="color:#888">Sin anuncios en el rango.</p>'}</div>
</section>

<section>
<h2>🔵 Resto T230 (2000-2006) · contexto generacional ({len(t230)})</h2>
<div class="cards">{''.join(card(r, 't230') for r in t230) or '<p style="color:#888">Sin anuncios.</p>'}</div>
</section>

<section>
<h2>⚪ Otras Celicas en España ({len(other)})</h2>
<div class="cards">{''.join(card(r, 'other') for r in other)}</div>
</section>

<footer>Generado por celica-tracker · ejecuta <code>python3 scrape.py &amp;&amp; python3 build_dashboard.py</code> para refrescar</footer>

<script>
const scatter = {json.dumps(scatter_data)};
const history = {json.dumps(history)};
const tooltip = (ctx) => {{
  const r = ctx.raw.r;
  return [`${{r.anio}} ${{r.modelo||''}}`, `${{r.precio.toLocaleString('es-ES')}} €`,
          `${{(r.km/1000).toFixed(0)}}k km · ${{r.ciudad||'?'}}`];
}};
new Chart(document.getElementById('scatter'), {{
  type: 'scatter',
  data: {{ datasets: [
    {{ label: 'Otras', data: scatter.other.map(r => ({{x: r.km/1000, y: r.precio, r: r}})),
       backgroundColor: '#666', pointRadius: 6 }},
    {{ label: 'T230 fuera 2002-2006', data: scatter.t230.map(r => ({{x: r.km/1000, y: r.precio, r: r}})),
       backgroundColor: '#4a9eff', pointRadius: 8 }},
    {{ label: '2002-2006 OBJETIVO', data: scatter.target.map(r => ({{x: r.km/1000, y: r.precio, r: r}})),
       backgroundColor: '#ff5252', pointRadius: 12, pointStyle: 'star' }},
  ]}},
  options: {{
    responsive: true, maintainAspectRatio: false,
    onClick: (e, els) => {{ if(els[0]) {{ const d = e.chart.data.datasets[els[0].datasetIndex].data[els[0].index]; if(d.r.url) window.open(d.r.url,'_blank'); }} }},
    plugins: {{ tooltip: {{ callbacks: {{ label: tooltip }} }}, legend: {{ labels: {{ color: '#ccc' }} }} }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Kilómetros (miles)', color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }},
      y: {{ title: {{ display: true, text: 'Precio (€)', color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }}
    }}
  }}
}});
new Chart(document.getElementById('history'), {{
  type: 'line',
  data: {{ labels: history.map(h => h.fecha),
           datasets: [
             {{ label: 'Mediana', data: history.map(h => h.mediana), borderColor: '#ffcc00', backgroundColor: '#ffcc0022', tension: 0.2, pointRadius: 5 }},
             {{ label: 'Min',     data: history.map(h => h.min), borderColor: '#4a9eff', borderDash:[4,4], pointRadius: 3 }},
             {{ label: 'Max',     data: history.map(h => h.max), borderColor: '#ff5252', borderDash:[4,4], pointRadius: 3 }},
           ]}},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }},
      y: {{ title: {{ display: true, text: '€', color: '#aaa' }}, ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }}
    }}
  }}
}});
{('document.getElementById("history").parentElement.innerHTML += \'<p style="color:#666;font-size:13px;margin-top:12px">Solo hay '+str(len(history))+' recolección. Ejecuta <code>scrape.py</code> en días distintos para ver tendencia.</p>\';' ) if len(history) <= 1 else ''}

// ---- Botones ----
const _btn   = document.getElementById('refresh-btn');
const _power = document.getElementById('power-btn');
const _log   = document.getElementById('refresh-log');
const _hint  = document.getElementById('refresh-hint');
const _panel = document.getElementById('logs-panel');
const _dot   = document.getElementById('logs-dot');
const _title = document.getElementById('logs-title');
const _modal = document.getElementById('modal-bg');
const SERVER_URL = 'http://127.0.0.1:8765/';
const _isHttp = location.protocol === 'http:' || location.protocol === 'https:';

function _showLogs(state, label) {{
  _panel.classList.add('active');
  _dot.className = 'dot ' + (state || '');
  _title.textContent = label || 'Logs';
}}
function closeModal() {{ _modal.classList.remove('active'); }}
function copyCmd(ev) {{
  const t = document.getElementById('modal-cmd').textContent;
  navigator.clipboard.writeText(t).then(() => {{
    const b = ev.target; const old = b.textContent;
    b.textContent = '✓ Copiado'; setTimeout(() => b.textContent = old, 1200);
  }}).catch(() => {{}});
}}

// El power-btn se autoetiqueta según contexto
function setPowerMode(mode) {{
  if (mode === 'stop') {{
    _power.textContent = '⏻ Apagar server';
    _power.className = 'ghost-btn danger';
    _power.dataset.mode = 'stop';
    _btn.disabled = false;
    _btn.textContent = '↻ Refrescar ahora';
    _hint.textContent = '';
  }} else {{
    _power.textContent = '▶ Arrancar server';
    _power.className = 'ghost-btn';
    _power.dataset.mode = 'start';
    _btn.disabled = true;
    _btn.textContent = '↻ Refrescar (necesita server)';
    _hint.textContent = 'El server no responde en :8765';
  }}
}}
setPowerMode(_isHttp ? 'stop' : 'start');

async function doPower() {{
  if (_power.dataset.mode === 'stop') {{
    if (!confirm('¿Apagar el server? Tendrás que volver a arrancarlo para refrescar.')) return;
    _power.disabled = true; _btn.disabled = true;
    _showLogs('live', 'Apagando server…');
    _log.textContent = 'Apagando server…';
    try {{
      const r = await fetch('/api/shutdown', {{method:'POST'}});
      if (r.status === 409) {{
        const j = await r.json();
        _log.textContent = '✗ ' + (j.error || 'no se puede apagar ahora');
        _power.disabled = false; _btn.disabled = false;
        return;
      }}
    }} catch(e) {{ /* esperable: la conexión muere */ }}
    _log.textContent = '👋 Server apagado.';
    _power.disabled = false;
    setPowerMode('start');
  }} else {{
    // Con socket activation systemd despierta el server al primer request.
    // Probamos primero — si no responde en ~3s, caemos al modal manual.
    _showLogs('live', 'Despertando server…');
    _log.textContent = 'Pidiendo a systemd que arranque celica-tracker.service…';
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 3500);
    try {{
      const r = await fetch(SERVER_URL + 'api/status', {{cache:'no-store', signal: ctrl.signal}});
      clearTimeout(t);
      if (r.ok) {{ _log.textContent = '✓ Server vivo, redirigiendo…'; location.href = SERVER_URL; return; }}
    }} catch(e) {{ /* timeout o conexión rechazada → no hay socket activation */ }}
    clearTimeout(t);
    _showLogs('err', 'Server no responde');
    _log.textContent = 'No hay socket activation ni server escuchando en :8765.\\nArráncalo a mano:';
    _modal.classList.add('active');
  }}
}}

async function doRefresh() {{
  _btn.disabled = true;
  _btn.innerHTML = '<span class="spin">↻</span> scrapeando…';
  _showLogs('live', 'Scrapeando…');
  _log.textContent = 'Lanzando scrape…';
  try {{
    const r = await fetch('/api/scrape', {{method:'POST'}});
    if (r.status === 409) {{
      _log.textContent = 'Ya hay un scrape en marcha, engancho al log existente…';
    }} else if (!r.ok) {{
      throw new Error('HTTP ' + r.status);
    }}
  }} catch(e) {{
    _log.textContent = 'Error: ' + e.message;
    _btn.disabled = false; _btn.textContent = '↻ Refrescar ahora';
    return;
  }}
  pollStatus();
}}
async function pollStatus() {{
  try {{
    const r = await fetch('/api/status');
    const s = await r.json();
    _log.textContent = (s.log || []).join('\\n');
    _log.scrollTop = _log.scrollHeight;
    if (s.running) {{
      setTimeout(pollStatus, 800);
    }} else {{
      _showLogs(s.ok ? 'ok' : 'err', s.ok ? 'Scrape OK' : 'Scrape con errores');
      _log.textContent += '\\n\\n' + (s.ok ? '✅ Listo, recargando…' : '⚠️  Terminó con errores, recargo igualmente…');
      setTimeout(() => location.reload(), 1500);
    }}
  }} catch(e) {{
    _log.textContent += '\\n[error sondeando: ' + e.message + ']';
    _btn.disabled = false; _btn.textContent = '↻ Refrescar ahora';
  }}
}}
// Si abro la pestaña mientras hay un scrape corriendo, engancharse en vivo
if (_isHttp) {{
  fetch('/api/status').then(r => r.json()).then(s => {{
    if (s && s.running) {{
      _btn.disabled = true;
      _btn.innerHTML = '<span class="spin">↻</span> scrapeando…';
      _showLogs('live', 'Scrapeando…');
      pollStatus();
    }}
  }}).catch(() => {{}});
}}
</script>
</body>
</html>"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"Dashboard → {HTML_PATH}")
    print(f"Abre con: xdg-open {HTML_PATH}")

if __name__ == "__main__":
    main()
