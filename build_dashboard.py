#!/usr/bin/env python3
"""Genera dashboard.html desde la BD Postgres y exporta el CSV de backup.

Calcula, además de los datos crudos, señales útiles para comprar:
- NUEVO       → anuncio visto por primera vez hoy (listings.first_seen == hoy).
- ↓ -X%       → bajada de precio respecto a la observación previa del anuncio.
- OPORTUNIDAD → precio ≤ 85% del esperado según un ajuste lineal precio~km del
                rango objetivo (solo precios realistas ≥ REALISTIC_MIN).
- días en venta → hoy − first_seen.

UX cliente: tema claro/oscuro, gráficas con zoom/pan y pantalla completa,
favoritos (localStorage), buscador/orden/filtros y animaciones.

El CSS y la lógica JS van en strings normales (no f-string) para no tener que
doblar llaves; solo se interpola la inyección de datos.
"""
import datetime, json, os, statistics, html
import db

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "dashboard.html")
REALISTIC_MIN = 1500   # piso para stats/gráficas: descarta 1€/450€ (broma/piezas)

# Iconos SVG (monocromos, heredan currentColor) — nada de emojis.
_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">{}</svg>')
ICON_LIST = _SVG.format('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>'
                        '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>'
                        '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>')
ICON_CHART = _SVG.format('<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>'
                         '<line x1="6" y1="20" x2="6" y2="14"/>')
ICON_SUN = ('<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/>'
            '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
            'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
ICON_MOON = ('<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round">'
             '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>')
ICON_PH = ('<svg class="ph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
           'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/>'
           '<circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>')
ICON_STAR = ('<svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 '
             '12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>')
ICON_REFRESH = _SVG.format('<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>'
                           '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>')
ICON_RESET = _SVG.format('<polyline points="1 4 1 10 7 10"/>'
                         '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>')
ICON_EXPAND = _SVG.format('<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>')


def linfit(xs, ys):
    """Ajuste lineal y = a + b*x por mínimos cuadrados. None si no hay datos."""
    n = len(xs)
    if n < 4:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    a = my - b * mx
    return a, b


def _days_between(a, b):
    try:
        return (datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days
    except Exception:
        return 0


# --------------------------------------------------------------- CSS / JS ----

CSS = """
  *{box-sizing:border-box;margin:0;padding:0}
  /* ---- NOCHE (PS2 "third place") por defecto ---- */
  :root{
    --bg-0:#03070e; --sky-1:#0a1b33; --sky-2:#061224; --sky-3:#020509; --glow:rgba(48,128,205,.24);
    --ink:#e9f1f8; --dim:#8ea6ba; --faint:#4d6376;
    --accent:#2fe089; --accent-2:#5fe6c0; --accent-deep:#1eb872; --accent-soft:rgba(47,224,137,.12);
    --line:rgba(186,216,236,.14); --line-2:rgba(186,216,236,.26); --tint:rgba(120,235,180,.05);
    --cloud-blend:screen; --cloud-opacity:.26; --scan-opacity:.5;
    --display:"Saira",system-ui,sans-serif; --mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
    /* mapeo a los tokens que usan los componentes del dashboard */
    --bg:var(--bg-0); --text:var(--ink); --muted:var(--dim); --muted2:var(--faint);
    --border:var(--line); --grid:var(--line);
    --panel:rgba(10,21,35,.55); --panel2:rgba(14,26,42,.5); --card:rgba(8,18,30,.82);
    --target:#ff6b6b; --t230:#4dabf7; --other:#8aa0b4; --gold:#ffd43b;
    --green:var(--accent); --orange:#ffa94d; --fav:#ffd43b;
  }
  /* ---- DÍA (cielo azul frutiger) ---- */
  [data-theme=light]{
    --bg-0:#cfe7f7; --sky-1:#57a8e6; --sky-2:#a6d6f2; --sky-3:#eaf6fd; --glow:rgba(255,255,255,.55);
    --ink:#0c2536; --dim:#3f5a6b; --faint:#7a93a2;
    --accent:#12a564; --accent-2:#18b873; --accent-deep:#0b7a48; --accent-soft:rgba(18,165,100,.10);
    --line:rgba(12,37,54,.15); --line-2:rgba(12,37,54,.3); --tint:rgba(12,37,54,.04);
    --cloud-blend:normal; --cloud-opacity:.85; --scan-opacity:.05;
    --panel:rgba(255,255,255,.72); --panel2:rgba(255,255,255,.55); --card:rgba(255,255,255,.86);
    --grid:rgba(12,37,54,.12);
    --target:#e23b3b; --t230:#1f7fd4; --other:#5e7384; --gold:#c98a00; --orange:#d9791a; --fav:#e9a900;
  }
  html{color-scheme:dark;scroll-behavior:smooth}
  [data-theme=light] html,html[data-theme=light]{color-scheme:light}

  /* wipe radial entre temas (View Transitions) */
  ::view-transition-old(root){z-index:0}
  ::view-transition-new(root){z-index:1}
  ::view-transition-old(root),::view-transition-new(root){animation:none;mix-blend-mode:normal}
  html.vt body,html.vt .sky{transition:none!important}

  /* scrollbar verde */
  html{scrollbar-width:thin;scrollbar-color:var(--accent) transparent}
  ::-webkit-scrollbar{width:11px;height:11px}
  ::-webkit-scrollbar-track{background:transparent}
  ::-webkit-scrollbar-thumb{border:3px solid transparent;background-clip:padding-box;border-radius:999px;
    background-color:var(--accent-deep);background-image:linear-gradient(180deg,var(--accent-2),var(--accent) 50%,var(--accent-deep))}

  body{font-family:var(--mono);background:var(--bg-0);color:var(--ink);line-height:1.5;min-height:100vh;
    -webkit-font-smoothing:antialiased;position:relative;overflow-x:hidden;transition:background .5s,color .5s}

  /* cielo + nubes + grano (del portfolio) */
  .sky{position:fixed;inset:0;z-index:0;pointer-events:none;transition:background .5s;
    background:radial-gradient(120% 80% at 50% 6%,var(--glow),transparent 52%),
      radial-gradient(90% 60% at 50% 118%,var(--glow),transparent 60%),
      linear-gradient(180deg,var(--sky-1) 0%,var(--sky-2) 52%,var(--sky-3) 100%)}
  [data-theme=dark] .sky{background:radial-gradient(85% 65% at 50% 30%,var(--glow),transparent 56%),
      radial-gradient(135% 120% at 50% 46%,transparent 42%,rgba(0,0,0,.9) 100%),
      linear-gradient(180deg,var(--sky-1) 0%,var(--sky-2) 55%,var(--sky-3) 100%)}
  @keyframes cloud-roll{from{transform:translate3d(0,0,0) scale(1.15)}to{transform:translate3d(-6%,-2%,0) scale(1.3)}}
  .clouds{position:fixed;inset:-25%;z-index:0;pointer-events:none;background-size:cover;
    mix-blend-mode:var(--cloud-blend);opacity:var(--cloud-opacity);filter:blur(14px) contrast(1.08);will-change:transform;
    background-image:url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='760' height='760'><filter id='c'><feTurbulence type='fractalNoise' baseFrequency='0.0095' numOctaves='6' seed='9' stitchTiles='stitch'/><feColorMatrix type='matrix' values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.3 -0.42'/></filter><rect width='100%25' height='100%25' filter='url(%23c)'/></svg>");
    animation:cloud-roll 80s ease-in-out infinite alternate}
  .grain{position:fixed;inset:0;z-index:60;pointer-events:none;mix-blend-mode:overlay;opacity:var(--scan-opacity);
    background:repeating-linear-gradient(to bottom,rgba(255,255,255,.5) 0 1px,transparent 1px 3px)}

  /* figuras cromadas 3D reales (WebGL). Sin WebGL: no se muestra nada. */
  .gl{position:fixed;inset:0;z-index:1;pointer-events:none;opacity:0;transition:opacity .8s ease}
  .gl.ready{opacity:1}

  .wrap{position:relative;z-index:2;max-width:1200px;margin:0 auto;padding:26px clamp(16px,4vw,40px) 70px}

  h1{font-family:var(--display);font-style:italic;font-weight:800;font-size:clamp(1.8rem,4vw,2.5rem);
    line-height:1;letter-spacing:-.02em;margin-bottom:6px;display:inline-flex;align-items:baseline;gap:11px}
  h1::before{content:"\\25B8";color:var(--accent);font-size:.5em;transform:translateY(-.25em)}
  .sub{color:var(--dim);margin-bottom:20px;font-size:.78rem;letter-spacing:.04em}

  .reveal{opacity:0;transform:translateY(16px);transition:opacity .6s cubic-bezier(.16,1,.3,1),transform .6s cubic-bezier(.16,1,.3,1);transition-delay:var(--reveal-delay,0s)}
  .reveal.in{opacity:1;transform:none}

  .toolbar{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}
  .refresh-btn{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#04140d;border:0;
    padding:10px 18px;border-radius:9px;cursor:pointer;font-family:var(--mono);font-weight:700;font-size:13px;
    letter-spacing:.03em;display:inline-flex;align-items:center;gap:8px;
    box-shadow:0 6px 18px var(--accent-soft);transition:transform .12s,box-shadow .12s}
  .refresh-btn:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 8px 26px var(--accent-soft)}
  .refresh-btn:disabled{background:var(--line-2);color:var(--faint);cursor:wait;box-shadow:none;opacity:.8}
  .refresh-btn svg{width:16px;height:16px}
  .refresh-btn.loading svg{animation:spin 1s linear infinite}
  .pill{font-size:12px;color:var(--muted);background:var(--panel);border:1px solid var(--border);
    padding:7px 12px;border-radius:999px;display:inline-flex;align-items:center;gap:7px}
  .pill .dot{width:8px;height:8px;border-radius:50%;background:var(--muted2)}
  .pill .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
  .pill .dot.live{background:var(--gold);box-shadow:0 0 8px var(--gold);animation:pulse 1.2s ease-in-out infinite}
  .theme-btn{margin-left:auto;background:var(--panel);border:1px solid var(--border);color:var(--text);
    width:40px;height:40px;border-radius:10px;cursor:pointer;display:grid;place-items:center;
    transition:transform .15s,border-color .15s}
  .theme-btn:hover{transform:translateY(-1px) rotate(-12deg);border-color:var(--accent);color:var(--accent)}
  .theme-btn svg{width:18px;height:18px}
  .theme-btn .moon{display:none}
  [data-theme=light] .theme-btn .sun{display:none}
  [data-theme=light] .theme-btn .moon{display:block}
  @keyframes spin{to{transform:rotate(360deg)}}
  @keyframes pulse{50%{opacity:.4}}
  @keyframes fadeInUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr));gap:12px;margin-bottom:22px}
  .stat{background:var(--panel);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    border:1px solid var(--border);border-radius:14px;padding:15px 18px;animation:fadeInUp .4s ease both;cursor:pointer;
    transition:transform .12s,border-color .12s,box-shadow .12s}
  .stat:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 10px 24px rgba(0,0,0,.18)}
  .stat .num{display:block;font-family:var(--display);font-style:italic;font-weight:800;font-size:2rem;color:var(--ink);letter-spacing:-.01em}
  .stat.accent .num{color:var(--accent)}
  .stat.good .num{color:var(--accent)}
  .stat .lbl{display:block;font-size:10px;color:var(--muted);margin-top:6px;text-transform:uppercase;letter-spacing:.12em}

  /* tabs */
  .tabs{display:flex;gap:6px;margin:6px 0 18px;border-bottom:1px solid var(--border)}
  .tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--muted);
    padding:10px 16px;cursor:pointer;font-family:var(--mono);font-size:.78rem;font-weight:700;
    letter-spacing:.1em;text-transform:uppercase;transition:color .15s,border-color .15s}
  .tab:hover{color:var(--text)}
  .tab.active{color:var(--ink);border-bottom-color:var(--accent)}
  .tab svg{width:16px;height:16px;vertical-align:-3px;margin-right:7px}
  .hdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:9px;vertical-align:middle}
  .hdot.t{background:var(--target)}
  .hdot.b{background:var(--t230)}
  .hdot.o{background:var(--other)}
  .tabpane{display:none}
  .tabpane.active{display:block;animation:fadeInUp .35s ease both}

  .charts-main{display:grid;grid-template-columns:1fr;gap:18px}
  .charts-sub{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:18px;margin-top:18px}
  .charts-main .chart-wrap{height:430px}
  .panel{background:var(--panel);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    border:1px solid var(--border);border-radius:14px;padding:18px;animation:fadeInUp .4s ease both}
  .phead{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px}
  .phead h2{margin:0;font-family:var(--mono);font-size:.72rem;color:var(--accent);text-transform:uppercase;letter-spacing:.18em}
  .pbtns{display:flex;gap:6px}
  .icon{background:var(--panel2);border:1px solid var(--border);color:var(--muted);cursor:pointer;
    width:28px;height:28px;border-radius:8px;line-height:0;display:grid;place-items:center}
  .icon svg{width:15px;height:15px}
  .icon:hover{color:var(--accent);border-color:var(--accent)}
  .chart-wrap{position:relative;height:300px}
  .hint{font-size:11px;color:var(--muted2);margin:8px 0 0}

  .backdrop{position:fixed;inset:0;background:#0009;backdrop-filter:blur(2px);display:none;z-index:150}
  .backdrop.on{display:block}
  .panel.expanded{position:fixed;inset:3vh 3vw;z-index:200;margin:0;overflow:auto;box-shadow:0 20px 60px #000a}
  .panel.expanded .chart-wrap{height:calc(94vh - 96px)}

  .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 18px;
    background:var(--panel);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    border:1px solid var(--border);border-radius:12px;padding:12px 14px}
  .controls input[type=search],.controls select{background:var(--bg);color:var(--text);font-family:var(--mono);
    border:1px solid var(--border);border-radius:9px;padding:9px 12px;font-size:13px;outline:none}
  .controls input[type=search]{flex:1;min-width:180px}
  .controls input[type=search]:focus,.controls select:focus{border-color:var(--accent)}
  .controls label{font-size:12px;color:var(--muted);display:inline-flex;align-items:center;gap:6px;cursor:pointer}
  .controls .chk{display:flex;gap:12px;align-items:center;flex-wrap:wrap}

  section>h2{display:flex;align-items:center;gap:14px;margin:34px 0 16px;
    font-family:var(--mono);font-size:.72rem;letter-spacing:.2em;text-transform:uppercase;color:var(--accent)}
  section>h2 .rule{flex:1;height:1px;background:var(--line)}
  section>h2 .cnt{color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-variant-numeric:tabular-nums;letter-spacing:0}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,232px),1fr));gap:12px}
  .empty{color:var(--muted)}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:0;overflow:hidden;
    text-decoration:none;color:inherit;display:block;position:relative;animation:fadeInUp .35s ease both;
    transition:transform .12s,border-color .12s,box-shadow .12s}
  .card::after{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);
    box-shadow:0 0 12px var(--accent);transform:scaleY(0);transform-origin:top;z-index:3;
    transition:transform .28s cubic-bezier(.16,1,.3,1)}
  .card:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 10px 26px rgba(0,0,0,.22)}
  .card:hover::after{transform:scaleY(1)}
  .card.is-fav{border-color:var(--fav)}
  .thumb{position:relative;width:100%;aspect-ratio:16/10;overflow:hidden;
    background:linear-gradient(135deg,var(--panel2),var(--panel))}
  .thumb img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;transition:transform .35s}
  .card:hover .thumb img{transform:scale(1.05)}
  .thumb .ph{position:absolute;inset:0;margin:auto;width:42px;height:42px;color:var(--muted2);opacity:.32}
  .thumb::before{content:'';position:absolute;inset:0 0 55% 0;background:linear-gradient(#0008,transparent);pointer-events:none;z-index:1}
  .card .body{padding:12px 14px}
  .price{font-family:var(--display);font-style:italic;font-weight:800;font-size:1.5rem;color:var(--accent);letter-spacing:-.01em}
  .card.t230 .price{color:var(--t230)}
  .card.other .price{color:var(--dim)}
  .meta{font-size:14px;margin:7px 0 4px;color:var(--text);line-height:1.35}
  .meta .year{background:#ff6b6b22;padding:2px 8px;border-radius:5px;font-weight:700;font-size:13px}
  .card.t230 .meta .year{background:#4dabf722}
  .card.other .meta .year{background:#7c869622}
  .csub{font-size:12px;color:var(--muted);margin:0}
  .src{font-size:9px;padding:2px 6px;border-radius:4px;margin-left:8px;vertical-align:middle;
    font-weight:700;text-transform:uppercase;letter-spacing:.5px}
  .src-autoscout24{background:#ffd43b;color:#000}
  .src-wallapop{background:#36d3ff;color:#000}
  .src-coches{background:#ff6b6b;color:#fff}
  .badges{position:absolute;top:10px;right:10px;display:flex;flex-direction:column;gap:4px;align-items:flex-end}
  .badge{font-size:9px;font-weight:800;letter-spacing:.5px;padding:3px 7px;border-radius:999px;text-transform:uppercase}
  .badge.nuevo{background:#4dabf7;color:#04121f}
  .badge.op{background:var(--green);color:#04210f}
  .badge.drop{background:var(--orange);color:#2a1500}
  .fav{position:absolute;top:8px;left:8px;background:none;border:0;cursor:pointer;padding:2px;
    line-height:0;color:#fff;transition:transform .15s;z-index:2;filter:drop-shadow(0 1px 2px #000a)}
  .fav svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8}
  .fav:hover{transform:scale(1.25)}
  .fav.on{color:var(--fav);filter:drop-shadow(0 0 6px var(--fav))}
  .fav.on svg{fill:var(--fav);stroke:var(--fav)}
  footer{margin-top:48px;padding-top:22px;border-top:1px solid var(--line);color:var(--faint);
    font-size:.74rem;text-align:center;line-height:1.7;letter-spacing:.04em}

  .logs-panel{position:fixed;top:16px;right:16px;width:380px;max-height:calc(100vh - 32px);
    background:var(--panel);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    border:1px solid var(--border);border-radius:12px;box-shadow:0 8px 32px #000a;
    display:none;flex-direction:column;z-index:250;overflow:hidden}
  .logs-panel.active{display:flex}
  .logs-head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;
    border-bottom:1px solid var(--border);background:var(--panel2)}
  .logs-head .title{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-weight:600}
  .logs-head .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#555;margin-right:8px;vertical-align:middle}
  .logs-head .dot.live{background:var(--gold);box-shadow:0 0 8px var(--gold);animation:pulse 1.2s ease-in-out infinite}
  .logs-head .dot.ok{background:var(--green)}
  .logs-head .dot.err{background:var(--target)}
  .logs-head .close{background:none;border:0;color:var(--muted);font-size:18px;cursor:pointer;padding:0 4px}
  .logs-head .close:hover{color:var(--text)}
  .refresh-log{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted);padding:12px 14px;
    overflow-y:auto;white-space:pre-wrap;line-height:1.5;flex:1;min-height:80px}
  @media(max-width:1100px){.logs-panel{position:static;width:auto;max-height:280px;margin-bottom:20px;box-shadow:none}}
  @media(max-width:560px){
    .wrap{padding:18px 14px 56px}
    h1{font-size:1.6rem}
    .sub{font-size:.72rem}
    .stat{padding:13px 14px}
    .stat .num{font-size:1.55rem}
    .chart-wrap{height:260px}
    .charts-main .chart-wrap{height:320px}
    .tab{padding:9px 11px;font-size:.7rem;letter-spacing:.06em}
    .tab svg{margin-right:5px}
    .controls{padding:10px}
    .meta{font-size:13px}
    .price{font-size:1.35rem}
  }
  @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

JS_LOGIC = r"""
// ---- Tema ----
const THEME_KEY='celica_theme';
const themeBtn=document.getElementById('theme-btn');
function curTheme(){ return document.documentElement.getAttribute('data-theme')||'dark'; }
function applyChartTheme(){
  const cs=getComputedStyle(document.body);
  const text=(cs.getPropertyValue('--muted')||'#888').trim();
  const grid=(cs.getPropertyValue('--grid')||'#222').trim();
  Chart.defaults.color=text;
  Object.values(CHARTS).forEach(ch=>{
    if(!ch.options.scales) return;
    ['x','y'].forEach(ax=>{
      const s=ch.options.scales[ax]; if(!s) return;
      if(s.grid) s.grid.color=grid;
      if(s.ticks) s.ticks.color=text;
      if(s.title) s.title.color=text;
    });
    ch.update('none');
  });
}
function setTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  try{localStorage.setItem(THEME_KEY,t);}catch(e){}
  applyChartTheme();
}
if(themeBtn){
  themeBtn.addEventListener('click',(e)=>{
    const next=curTheme()==='light'?'dark':'light';
    if(!document.startViewTransition||matchMedia('(prefers-reduced-motion: reduce)').matches){setTheme(next);return;}
    const x=e.clientX||innerWidth-40, y=e.clientY||40;
    const end=Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y));
    document.documentElement.classList.add('vt');
    const vt=document.startViewTransition(()=>setTheme(next));
    vt.ready.then(()=>document.documentElement.animate(
      {clipPath:[`circle(0px at ${x}px ${y}px)`,`circle(${end}px at ${x}px ${y}px)`]},
      {duration:560,easing:'cubic-bezier(.16,1,.3,1)',pseudoElement:'::view-transition-new(root)'}));
    vt.finished.finally(()=>document.documentElement.classList.remove('vt'));
  });
}

// ---- Gráficas ----
Chart.defaults.font.family="-apple-system, system-ui, sans-serif";
Chart.defaults.font.size=12;
const CHARTS={};
const C={target:'#ff6b6b',t230:'#4dabf7',other:'#7c8696',gold:'#ffd43b',min:'#4dabf7',max:'#ff7676'};
const eur=v=>(v==null?'?':Math.round(v).toLocaleString('es-ES')+' €');
// Sin rueda (el scroll infinito era feo): arrastrar selecciona un rango y hace
// zoom a esa zona; los límites 'original' impiden alejarse más allá de los datos.
const zoomCfg=(mode)=>({
  pan:{enabled:false},
  zoom:{wheel:{enabled:false},pinch:{enabled:true},
        drag:{enabled:true,backgroundColor:'rgba(77,171,247,0.18)',borderColor:'#4dabf7',borderWidth:1},
        mode:mode},
  limits:{x:{min:'original',max:'original'},y:{min:'original',max:'original'}}
});
function resetZoom(id){ const c=CHARTS[id]; if(c&&c.resetZoom) c.resetZoom(); }

const scTip=(ctx)=>{ const r=ctx.raw.r;
  const l=[`${r.anio||'?'} · ${r.modelo||''}`.trim(),eur(r.precio),`${(r.km/1000).toFixed(0)}k km · ${r.ciudad||'?'}`];
  if(r.tag) l.push(r.tag); return l; };

CHARTS.scatter=new Chart(document.getElementById('scatter'),{
  type:'scatter',
  data:{datasets:[
    {label:'Otras',data:scatter.other.map(r=>({x:r.km/1000,y:r.precio,r})),
     backgroundColor:C.other+'cc',borderColor:'#0d0f14',borderWidth:1,pointRadius:5,pointHoverRadius:7},
    {label:'T230 fuera 02-06',data:scatter.t230.map(r=>({x:r.km/1000,y:r.precio,r})),
     backgroundColor:C.t230+'dd',borderColor:'#0d0f14',borderWidth:1,pointRadius:6,pointHoverRadius:9},
    {label:'2002-2006 objetivo',data:scatter.target.map(r=>({x:r.km/1000,y:r.precio,r})),
     backgroundColor:C.target,borderColor:'#fff',borderWidth:1.2,pointRadius:7,pointHoverRadius:10},
  ]},
  options:{responsive:true,maintainAspectRatio:false,
    interaction:{mode:'nearest',intersect:true},
    onClick:(e,els)=>{if(els[0]){const d=e.chart.data.datasets[els[0].datasetIndex].data[els[0].index];if(d.r.url)window.open(d.r.url,'_blank');}},
    onHover:(e,els)=>{e.native.target.style.cursor=els[0]?'pointer':'default';},
    plugins:{legend:{labels:{usePointStyle:true,pointStyle:'circle',boxWidth:8,padding:16}},
      tooltip:{backgroundColor:'#0a0c11',borderColor:'#262c3a',borderWidth:1,padding:10,titleColor:'#fff',bodyColor:'#cfd5df',callbacks:{label:scTip}},
      zoom:zoomCfg('xy')},
    scales:{x:{title:{display:true,text:'Kilómetros (miles)'},grid:{},ticks:{callback:v=>Math.round(v)+'k'}},
      y:{title:{display:true,text:'Precio'},grid:{},ticks:{callback:v=>Math.round(v/1000)+'k €'}}}}
});

CHARTS.history=new Chart(document.getElementById('history'),{
  type:'line',
  data:{labels:history.map(h=>h.fecha),datasets:[
    {label:'q1',data:history.map(h=>h.q1),borderColor:'transparent',pointRadius:0,fill:false},
    {label:'rango intercuartil',data:history.map(h=>h.q3),borderColor:'#ffd43b22',backgroundColor:'#ffd43b1f',pointRadius:0,fill:'-1',tension:.3},
    {label:'mediana',data:history.map(h=>h.mediana),borderColor:C.gold,borderWidth:3,backgroundColor:C.gold,pointRadius:3,pointHoverRadius:5,tension:.3},
    {label:'mín',data:history.map(h=>h.min),borderColor:C.min+'88',borderWidth:1.5,borderDash:[4,4],pointRadius:0,tension:.3},
    {label:'máx',data:history.map(h=>h.max),borderColor:C.max+'88',borderWidth:1.5,borderDash:[4,4],pointRadius:0,tension:.3},
  ]},
  options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
    plugins:{legend:{labels:{usePointStyle:true,pointStyle:'line',boxWidth:18,padding:14,filter:i=>i.text!=='q1'}},
      tooltip:{backgroundColor:'#0a0c11',borderColor:'#262c3a',borderWidth:1,padding:10,titleColor:'#fff',bodyColor:'#cfd5df',
        filter:i=>i.dataset.label!=='q1',callbacks:{label:c=>`${c.dataset.label}: ${eur(c.parsed.y)}`}},
      zoom:zoomCfg('x')},
    scales:{x:{grid:{},ticks:{maxRotation:60,minRotation:45,autoSkip:true,maxTicksLimit:14}},
      y:{grid:{},ticks:{callback:v=>Math.round(v/1000)+'k €'}}}}
});

// Histograma de precios (rango objetivo)
(function(){
  const vals=scatter.target.map(r=>r.precio).filter(v=>v>=1500).sort((a,b)=>a-b);
  let labels=[],counts=[];
  if(vals.length){
    const lo=Math.floor(vals[0]/1000)*1000, hi=Math.ceil(vals[vals.length-1]/1000)*1000;
    const step=Math.max(1000,Math.round((hi-lo)/8/1000)*1000);
    for(let b=lo;b<hi;b+=step){ labels.push((b/1000)+'–'+((b+step)/1000)+'k'); counts.push(vals.filter(v=>v>=b&&v<b+step).length); }
  }
  CHARTS.dist=new Chart(document.getElementById('dist'),{
    type:'bar',data:{labels,datasets:[{label:'anuncios',data:counts,backgroundColor:C.target+'cc',borderRadius:5}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#0a0c11',borderColor:'#262c3a',borderWidth:1,padding:10,titleColor:'#fff',bodyColor:'#cfd5df'}},
      scales:{x:{grid:{}},y:{grid:{},ticks:{precision:0}}}}});
})();

// Mediana por año
CHARTS.year=new Chart(document.getElementById('byyear'),{
  type:'bar',data:{labels:byYear.map(y=>y.anio),
    datasets:[{label:'mediana',data:byYear.map(y=>y.mediana),backgroundColor:C.gold+'cc',borderRadius:5}]},
  options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},
      tooltip:{backgroundColor:'#0a0c11',borderColor:'#262c3a',borderWidth:1,padding:10,titleColor:'#fff',bodyColor:'#cfd5df',
        callbacks:{label:c=>eur(c.parsed.y)+'  ('+byYear[c.dataIndex].n+' anuncios)'}}},
    scales:{x:{grid:{}},y:{grid:{},ticks:{callback:v=>Math.round(v/1000)+'k €'}}}}
});

applyChartTheme();

// ---- Ampliar panel ----
function toggleExpand(btn){
  const p=btn.closest('.panel'); const open=p.classList.contains('expanded');
  document.querySelectorAll('.panel.expanded').forEach(x=>x.classList.remove('expanded'));
  const bd=document.getElementById('backdrop');
  if(open){bd.classList.remove('on');}else{p.classList.add('expanded');bd.classList.add('on');}
  setTimeout(()=>Object.values(CHARTS).forEach(c=>c.resize()),90);
}
function closeExpand(){
  document.querySelectorAll('.panel.expanded').forEach(x=>x.classList.remove('expanded'));
  document.getElementById('backdrop').classList.remove('on');
  setTimeout(()=>Object.values(CHARTS).forEach(c=>c.resize()),90);
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeExpand();});

// ---- Favoritos (localStorage) ----
const FAV_KEY='celica_favs';
let favs=new Set(); try{favs=new Set(JSON.parse(localStorage.getItem(FAV_KEY)||'[]'));}catch(e){}
function saveFavs(){ try{localStorage.setItem(FAV_KEY,JSON.stringify([...favs]));}catch(e){} }
function paintFav(card){
  const id=card.getAttribute('data-fav-id'); const on=favs.has(id);
  card.classList.toggle('is-fav',on);
  const b=card.querySelector('.fav'); if(b){b.classList.toggle('on',on);}
}
document.querySelectorAll('.card').forEach(paintFav);
document.addEventListener('click',e=>{
  const b=e.target.closest('.fav'); if(!b) return;
  e.preventDefault(); e.stopPropagation();
  const card=b.closest('.card'); const id=card.getAttribute('data-fav-id');
  if(favs.has(id))favs.delete(id); else favs.add(id);
  saveFavs(); paintFav(card); apply();
});

// ---- Buscador / orden / filtros ----
const q=document.getElementById('q');
const sortSel=document.getElementById('sort');
const onlyOp=document.getElementById('only-op');
const onlyFav=document.getElementById('only-fav');
const favCount=document.getElementById('fav-count');
const srcChks=Array.from(document.querySelectorAll('.src-chk'));
const containers=Array.from(document.querySelectorAll('.cards'));
function num(card,attr,def){const v=card.getAttribute(attr);return v===''||v==null?def:parseFloat(v);}
function apply(){
  const term=(q.value||'').toLowerCase().trim();
  const srcOn=new Set(srcChks.filter(c=>c.checked).map(c=>c.value));
  const opOnly=onlyOp.checked, favOnly=onlyFav.checked, key=sortSel.value;
  containers.forEach(cont=>{
    const cards=Array.from(cont.querySelectorAll('.card')); let visible=0;
    cards.forEach(c=>{
      const okTerm=!term||(c.getAttribute('data-text')||'').includes(term);
      const okSrc=srcOn.has(c.getAttribute('data-fuente'));
      const okOp=!opOnly||c.getAttribute('data-op')==='1';
      const okFav=!favOnly||favs.has(c.getAttribute('data-fav-id'));
      const show=okTerm&&okSrc&&okOp&&okFav;
      c.style.display=show?'':'none'; if(show)visible++;
    });
    const sorted=cards.slice().sort((a,b)=>{switch(key){
      case 'precio-desc':return num(b,'data-precio',-1)-num(a,'data-precio',-1);
      case 'km-asc':return num(a,'data-km',1e9)-num(b,'data-km',1e9);
      case 'anio-desc':return num(b,'data-anio',0)-num(a,'data-anio',0);
      case 'nuevos':return num(a,'data-dias',1e9)-num(b,'data-dias',1e9);
      case 'bajada':return num(b,'data-drop',0)-num(a,'data-drop',0);
      default:return num(a,'data-precio',1e12)-num(b,'data-precio',1e12);}});
    sorted.forEach(c=>cont.appendChild(c));
    const cnt=cont.parentElement.querySelector('.cnt'); if(cnt)cnt.textContent=visible;
  });
  if(favCount)favCount.textContent=favs.size;
}
[q,sortSel,onlyOp,onlyFav,...srcChks].forEach(el=>el&&el.addEventListener('input',apply));

// entrada escalonada de tarjetas
containers.forEach(cont=>Array.from(cont.querySelectorAll('.card')).forEach((c,i)=>{c.style.animationDelay=Math.min(i*18,360)+'ms';}));
apply();

// ---- Tabs ----
const TAB_KEY='celica_tab';
function showTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('active',p.id==='tab-'+name));
  try{localStorage.setItem(TAB_KEY,name);}catch(e){}
  if(name==='graficas') setTimeout(()=>Object.values(CHARTS).forEach(c=>c.resize()),60);
}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>showTab(t.dataset.tab)));
(function(){let t='listado';try{t=localStorage.getItem(TAB_KEY)||'listado';}catch(e){}showTab(t);})();

// ---- Stats clicables ----
function statAction(a){
  if(a==='mediana'){showTab('graficas');return;}
  showTab('listado');
  if(a==='barato')sortSel.value='precio-asc';
  else if(a==='caro')sortSel.value='precio-desc';
  else if(a==='op')onlyOp.checked=true;
  else if(a==='nuevos')sortSel.value='nuevos';
  else if(a==='all'){q.value='';onlyOp.checked=false;onlyFav.checked=false;srcChks.forEach(c=>c.checked=true);sortSel.value='precio-asc';}
  apply();
  window.scrollTo({top:0,behavior:'smooth'});
}

// ---- Refrescar + estado del auto-scrape ----
const _btn=document.getElementById('refresh-btn');
const _log=document.getElementById('refresh-log');
const _panel=document.getElementById('logs-panel');
const _dot=document.getElementById('logs-dot');
const _title=document.getElementById('logs-title');
const _auto=document.getElementById('auto-pill');
const _autoDot=document.getElementById('auto-dot');
const _isHttp=location.protocol==='http:'||location.protocol==='https:';
function _showLogs(state,label){_panel.classList.add('active');_dot.className='dot '+(state||'');_title.textContent=label||'Logs';}
function setBtnLoading(on){_btn.disabled=on;_btn.classList.toggle('loading',on);const t=_btn.querySelector('.btxt');if(t)t.textContent=on?'scrapeando…':'Refrescar ahora';}
const hhmm=ts=>{const d=new Date(ts*1000);return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');};
function renderAuto(s){
  if(!_auto)return;
  if(s&&s.auto){_autoDot.className='dot '+(s.running?'live':'on');
    if(s.running)_auto.lastChild.textContent=' auto-scrape en marcha…';
    else if(s.next_scrape_at)_auto.lastChild.textContent=' próximo auto-scrape ~'+hhmm(s.next_scrape_at);
    else _auto.lastChild.textContent=' auto-scrape activo';
  }else{_autoDot.className='dot';_auto.lastChild.textContent=' auto-scrape off';}
}
async function doRefresh(){
  setBtnLoading(true);
  _showLogs('live','Scrapeando…');_log.textContent='Lanzando scrape…';
  try{const r=await fetch('/api/scrape',{method:'POST'});
    if(r.status===409){_log.textContent='Ya hay un scrape en marcha, engancho al log…';}
    else if(!r.ok){throw new Error('HTTP '+r.status);}
  }catch(e){_log.textContent='Error: '+e.message;setBtnLoading(false);return;}
  pollStatus();
}
async function pollStatus(){
  try{const r=await fetch('/api/status');const s=await r.json();renderAuto(s);
    _log.textContent=(s.log||[]).join('\n');_log.scrollTop=_log.scrollHeight;
    if(s.running){setTimeout(pollStatus,800);}
    else{_showLogs(s.ok?'ok':'err',s.ok?'Scrape OK':'Scrape con errores');
      _log.textContent+='\n\n'+(s.ok?'Listo, recargando…':'Terminó con errores, recargo igualmente…');
      setTimeout(()=>location.reload(),1500);}
  }catch(e){_log.textContent+='\n[error sondeando: '+e.message+']';setBtnLoading(false);}
}
if(_isHttp){
  fetch('/api/status').then(r=>r.json()).then(s=>{renderAuto(s);
    if(s&&s.running){setBtnLoading(true);_showLogs('live','Scrapeando…');pollStatus();}
  }).catch(()=>renderAuto(null));
  setInterval(()=>{if(!_btn.disabled)fetch('/api/status').then(r=>r.json()).then(renderAuto).catch(()=>{});},60000);
}else{renderAuto(null);}

// ---- Reveal al hacer scroll + parallax de nubes/figuras ----
const _reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
(function(){
  const items=document.querySelectorAll('.reveal');
  if(_reduce||!('IntersectionObserver' in window)){items.forEach(el=>el.classList.add('in'));return;}
  const io=new IntersectionObserver((ents,obs)=>{let n=0;ents.forEach(en=>{if(!en.isIntersecting)return;
    en.target.style.setProperty('--reveal-delay',(n++*0.06)+'s');en.target.classList.add('in');obs.unobserve(en.target);});},
    {threshold:0.12,rootMargin:'0px 0px -6% 0px'});
  items.forEach(el=>io.observe(el));
})();
if(!_reduce&&matchMedia('(pointer:fine)').matches){
  let raf=0,tx=0;
  addEventListener('pointermove',e=>{tx=(e.clientX/innerWidth-0.5)*18;if(raf)return;
    raf=requestAnimationFrame(()=>{document.body.style.setProperty('--px',tx.toFixed(2)+'px');raf=0;});},{passive:true});
}
"""


def main():
    conn = db.connect()
    db.init(conn)
    today = db.latest_date(conn) or datetime.date.today().isoformat()
    latest = db.rows_for_date(conn, today)

    target = sorted([r for r in latest if r["anio"] and 2002 <= r["anio"] <= 2006],
                    key=lambda x: x["precio_eur"] or 0)
    t230 = sorted([r for r in latest if r["anio"] and 2000 <= r["anio"] <= 2006
                   and not (2002 <= r["anio"] <= 2006)],
                  key=lambda x: x["precio_eur"] or 0)
    other = sorted([r for r in latest if not (r["anio"] and 2000 <= r["anio"] <= 2006)
                    and r["precio_eur"] and r["precio_eur"] < 50000],
                   key=lambda x: x["precio_eur"] or 0)

    # ajuste precio~km del rango objetivo realista (para detectar oportunidades)
    fit_pts = [(r["km"], r["precio_eur"]) for r in target
               if r["km"] and r["precio_eur"] and r["precio_eur"] >= REALISTIC_MIN]
    fit = linfit([p[0] for p in fit_pts], [p[1] for p in fit_pts])

    def annotate(rows, is_target=False):
        for r in rows:
            r["nuevo"] = (r.get("first_seen") == today)
            r["dias"] = _days_between(today, r.get("first_seen") or today)
            prev = db.prev_price(conn, r["key"], today)
            r["drop_pct"] = 0
            if prev and r["precio_eur"] and r["precio_eur"] < prev:
                r["drop_pct"] = round((prev - r["precio_eur"]) / prev * 100)
            r["op"] = False
            if is_target and fit and r["km"] and r["precio_eur"] and r["precio_eur"] >= REALISTIC_MIN:
                pred = fit[0] + fit[1] * r["km"]
                r["op"] = pred > 0 and r["precio_eur"] <= 0.85 * pred
    annotate(target, is_target=True)
    annotate(t230)
    annotate(other)

    prices_real = [r["precio_eur"] for r in target if r["precio_eur"] and r["precio_eur"] >= REALISTIC_MIN]
    n_op = sum(1 for r in target if r["op"])
    n_nuevos = sum(1 for r in target if r["nuevo"])

    def fmt(v):
        return f"{v:,}".replace(",", ".")

    if prices_real:
        stats_html = (
            f'<div class="stat" onclick="statAction(\'all\')"><span class="num">{len(target)}</span><span class="lbl">anuncios 2002-2006</span></div>'
            f'<div class="stat" onclick="statAction(\'barato\')"><span class="num">{fmt(min(prices_real))}€</span><span class="lbl">más barato</span></div>'
            f'<div class="stat accent" onclick="statAction(\'mediana\')"><span class="num">{fmt(int(statistics.median(prices_real)))}€</span><span class="lbl">mediana</span></div>'
            f'<div class="stat" onclick="statAction(\'caro\')"><span class="num">{fmt(max(prices_real))}€</span><span class="lbl">más caro</span></div>'
            f'<div class="stat good" onclick="statAction(\'op\')"><span class="num">{n_op}</span><span class="lbl">oportunidades</span></div>'
            f'<div class="stat" onclick="statAction(\'nuevos\')"><span class="num">{n_nuevos}</span><span class="lbl">nuevos hoy</span></div>'
        )
    else:
        stats_html = '<div class="stat"><span class="num">0</span><span class="lbl">sin datos</span></div>'

    by_src = {}
    for r in latest:
        by_src[r["fuente"]] = by_src.get(r["fuente"], 0) + 1
    src_summary = " · ".join(f"{k}: {v}" for k, v in sorted(by_src.items()))

    # histórico: mediana/cuartiles/min/max por fecha (rango objetivo realista)
    by_date = {}
    for r in db.observations_join(conn):
        if r["anio"] and 2002 <= r["anio"] <= 2006 and r["precio_eur"] and r["precio_eur"] >= REALISTIC_MIN:
            by_date.setdefault(r["fecha"], []).append(r["precio_eur"])
    history = []
    for d in sorted(by_date):
        ps = sorted(by_date[d])
        q1 = q3 = statistics.median(ps)
        if len(ps) >= 2:
            qs = statistics.quantiles(ps, n=4)
            q1, q3 = qs[0], qs[2]
        history.append({"fecha": d, "mediana": statistics.median(ps),
                        "q1": q1, "q3": q3, "min": min(ps), "max": max(ps), "n": len(ps)})

    # mediana por año (rango objetivo realista)
    year_map = {}
    for r in target:
        if r["anio"] and r["precio_eur"] and r["precio_eur"] >= REALISTIC_MIN:
            year_map.setdefault(r["anio"], []).append(r["precio_eur"])
    by_year = [{"anio": y, "mediana": statistics.median(year_map[y]), "n": len(year_map[y])}
               for y in sorted(year_map)]

    def scatter_rows(rows):
        out = []
        for r in rows:
            if not (r["km"] and r["precio_eur"]):
                continue
            tags = []
            if r.get("nuevo"): tags.append("NUEVO")
            if r.get("op"): tags.append("OPORTUNIDAD")
            if r.get("drop_pct"): tags.append(f"↓ -{r['drop_pct']}%")
            out.append({"km": r["km"], "precio": r["precio_eur"], "anio": r["anio"],
                        "modelo": r["modelo"], "ciudad": r["ciudad"], "url": r["url"],
                        "tag": " · ".join(tags)})
        return out
    scatter_data = {"target": scatter_rows(target), "t230": scatter_rows(t230), "other": scatter_rows(other)}

    def card(r, klass=""):
        precio = f'{fmt(r["precio_eur"])}€' if r["precio_eur"] else "?"
        km = f'{r["km"]//1000}k km' if r["km"] else "? km"
        ciudad = (r["ciudad"] or "").strip() or "?"
        src = (r["fuente"] or "").split(".")[0]
        text = " ".join(str(x) for x in [r.get("modelo"), r.get("ciudad"),
                                         r.get("anio"), r.get("fuente")] if x).lower()
        badges = ""
        if r.get("nuevo"): badges += '<span class="badge nuevo">nuevo</span>'
        if r.get("op"): badges += '<span class="badge op">oportunidad</span>'
        if r.get("drop_pct"): badges += f'<span class="badge drop">↓ {r["drop_pct"]}%</span>'
        badges_html = f'<div class="badges">{badges}</div>' if badges else ""
        dias = r.get("dias", 0)
        dias_txt = "hoy" if dias <= 0 else f"hace {dias} d"
        url = r["url"] or ""
        foto = (r.get("foto") or "").strip()
        if foto:
            thumb = (f'<div class="thumb">{ICON_PH}<img loading="lazy" referrerpolicy="no-referrer" '
                     f'src="{html.escape(foto)}" alt="" onerror="this.remove()"></div>')
        else:
            thumb = f'<div class="thumb">{ICON_PH}</div>'
        return (
            f'<a class="card {klass}" href="{html.escape(url)}" target="_blank"'
            f' data-fav-id="{html.escape(url)}"'
            f' data-precio="{r["precio_eur"] or ""}" data-km="{r["km"] or ""}"'
            f' data-anio="{r["anio"] or ""}" data-fuente="{html.escape(src)}"'
            f' data-op="{1 if r.get("op") else 0}" data-nuevo="{1 if r.get("nuevo") else 0}"'
            f' data-drop="{r.get("drop_pct", 0)}" data-dias="{dias}"'
            f' data-text="{html.escape(text)}">'
            f'{thumb}'
            f'<button class="fav" title="Favorito" aria-label="Favorito">{ICON_STAR}</button>'
            f'{badges_html}'
            f'<div class="body">'
            f'<div class="price">{precio}<span class="src src-{html.escape(src)}">{html.escape(r["fuente"] or "")}</span></div>'
            f'<div class="meta"><span class="year">{r["anio"] or "?"}</span> · '
            f'<span>{html.escape((r["modelo"] or "").strip())}</span></div>'
            f'<div class="csub">{html.escape(ciudad)} · {km} · {dias_txt}</div>'
            f'</div>'
            f'</a>'
        )

    cards_target = "".join(card(r, "target") for r in target) or '<p class="empty">Sin anuncios en el rango.</p>'
    cards_t230 = "".join(card(r, "t230") for r in t230) or '<p class="empty">Sin anuncios.</p>'
    cards_other = "".join(card(r, "other") for r in other)

    def panel(title, canvas_id, hint="", zoomable=True):
        h = f'<p class="hint">{hint}</p>' if hint else ""
        reset = (f'<button class="icon" onclick="resetZoom(\'{canvas_id}\')" title="Quitar zoom">{ICON_RESET}</button>'
                 if zoomable else "")
        return (f'<div class="panel"><div class="phead"><h2>{title}</h2><div class="pbtns">'
                f'{reset}'
                f'<button class="icon" onclick="toggleExpand(this)" title="Ampliar">{ICON_EXPAND}</button>'
                f'</div></div><div class="chart-wrap"><canvas id="{canvas_id}"></canvas></div>{h}</div>')

    zoom_hint = "arrastra para seleccionar un rango · usa el botón para reiniciar"
    parts = []
    parts.append('<!doctype html>\n<html lang="es" data-theme="dark">\n<head>\n<meta charset="utf-8">\n')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">\n')
    parts.append("<title>Toyota Celica · mercado España</title>\n")
    parts.append('<link rel="preconnect" href="https://fonts.googleapis.com">\n')
    parts.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n')
    parts.append('<link href="https://fonts.googleapis.com/css2?family=Saira:ital,wght@0,600;0,700;0,800;'
                 '1,600;1,700;1,800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">\n')
    parts.append("<script>(function(){try{var t=localStorage.getItem('celica_theme')||"
                 "(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');"
                 "document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>\n")
    parts.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>\n')
    parts.append('<script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>\n')
    parts.append('<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>\n')
    parts.append('<script type="module" src="/scene.js"></script>\n')
    parts.append(f"<style>{CSS}</style>\n</head>\n<body>\n")
    parts.append('<div class="sky" aria-hidden="true"></div>\n')
    parts.append('<div class="clouds" aria-hidden="true"></div>\n')
    parts.append('<canvas class="gl" aria-hidden="true"></canvas>\n')
    parts.append('<div class="grain" aria-hidden="true"></div>\n')
    parts.append('<div id="backdrop" class="backdrop" onclick="closeExpand()"></div>\n')
    parts.append('<div class="wrap">\n')
    parts.append('<h1>Toyota Celica · mercado España</h1>\n')
    parts.append(f'<div class="sub">Última actualización: {today} · {len(latest)} anuncios · {html.escape(src_summary)}</div>\n')

    parts.append('<div class="toolbar">\n')
    parts.append(f'  <button id="refresh-btn" class="refresh-btn" onclick="doRefresh()">{ICON_REFRESH}<span class="btxt">Refrescar ahora</span></button>\n')
    parts.append('  <span id="auto-pill" class="pill"><span id="auto-dot" class="dot"></span><span> auto-scrape</span></span>\n')
    parts.append(f'  <button id="theme-btn" class="theme-btn" title="Cambiar tema" aria-label="Cambiar tema">{ICON_SUN}{ICON_MOON}</button>\n')
    parts.append('</div>\n')

    parts.append('<aside id="logs-panel" class="logs-panel">\n')
    parts.append('  <div class="logs-head"><span><span id="logs-dot" class="dot"></span>'
                 '<span id="logs-title" class="title">Logs</span></span>'
                 '<button class="close" onclick="document.getElementById(\'logs-panel\').classList.remove(\'active\')">×</button></div>\n')
    parts.append('  <div id="refresh-log" class="refresh-log"></div>\n</aside>\n')

    parts.append(f'<div class="stats">{stats_html}</div>\n')

    parts.append('<div class="tabs">\n'
                 f'  <button class="tab" data-tab="listado">{ICON_LIST}Listado</button>\n'
                 f'  <button class="tab" data-tab="graficas">{ICON_CHART}Gráficas</button>\n'
                 '</div>\n')

    parts.append('<div id="tab-listado" class="tabpane">\n')
    parts.append('<div class="controls">\n')
    parts.append('  <input id="q" type="search" placeholder="Buscar modelo, ciudad, año…">\n')
    parts.append('  <select id="sort">'
                 '<option value="precio-asc">Precio: barato primero</option>'
                 '<option value="precio-desc">Precio: caro primero</option>'
                 '<option value="km-asc">Menos km</option>'
                 '<option value="anio-desc">Más nuevo (año)</option>'
                 '<option value="nuevos">Recién listados</option>'
                 '<option value="bajada">Mayor bajada</option></select>\n')
    parts.append('  <span class="chk">'
                 '<label><input type="checkbox" class="src-chk" value="autoscout24" checked> autoscout24</label>'
                 '<label><input type="checkbox" class="src-chk" value="wallapop" checked> wallapop</label>'
                 '<label><input type="checkbox" class="src-chk" value="coches" checked> coches</label>'
                 '<label><input type="checkbox" id="only-op"> solo oportunidades</label>'
                 '<label><input type="checkbox" id="only-fav"> favoritos (<span id="fav-count">0</span>)</label>'
                 '</span>\n')
    parts.append('</div>\n')

    parts.append('<section><h2 class="reveal"><span class="hdot t"></span><span>Rango objetivo 2002-2006</span>'
                 f'<span class="rule"></span><span class="cnt">{len(target)}</span></h2>'
                 f'<div class="cards">{cards_target}</div></section>\n')
    parts.append('<section><h2 class="reveal"><span class="hdot b"></span><span>Resto T230 2000-2006 · contexto</span>'
                 f'<span class="rule"></span><span class="cnt">{len(t230)}</span></h2>'
                 f'<div class="cards">{cards_t230}</div></section>\n')
    parts.append('<section><h2 class="reveal"><span class="hdot o"></span><span>Otras Celicas en España</span>'
                 f'<span class="rule"></span><span class="cnt">{len(other)}</span></h2>'
                 f'<div class="cards">{cards_other}</div></section>\n')
    parts.append('</div>\n')  # /tab-listado

    parts.append('<div id="tab-graficas" class="tabpane">\n')
    parts.append('  <div class="charts-main">\n')
    parts.append("    " + panel("Precio vs kilómetros", "scatter", zoom_hint) + "\n")
    parts.append("    " + panel("Histórico precio 2002-2006", "history", zoom_hint) + "\n")
    parts.append('  </div>\n')
    parts.append('  <div class="charts-sub">\n')
    parts.append("    " + panel("Distribución de precios", "dist", zoomable=False) + "\n")
    parts.append("    " + panel("Mediana por año", "byyear", zoomable=False) + "\n")
    parts.append('  </div>\n')
    parts.append('</div>\n')  # /tab-graficas

    parts.append('<footer>Generado por celica-tracker · datos en PostgreSQL · '
                 'auto-scrape ~cada 2 h (con jitter)</footer>\n')
    parts.append('</div>\n')  # /wrap

    parts.append("<script>\n")
    parts.append(f"const scatter = {json.dumps(scatter_data)};\n")
    parts.append(f"const history = {json.dumps(history)};\n")
    parts.append(f"const byYear = {json.dumps(by_year)};\n")
    parts.append(JS_LOGIC)
    parts.append("\n</script>\n</body>\n</html>")

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    n_csv = db.export_csv(conn)
    conn.close()
    print(f"Dashboard → {HTML_PATH}")
    print(f"CSV backup → {db.CSV_PATH} ({n_csv} filas)")


if __name__ == "__main__":
    main()
