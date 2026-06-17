#!/usr/bin/env python3
"""Capa de datos del celica-tracker sobre PostgreSQL (psycopg 3).

Postgres es la fuente de verdad; `celica_prices.csv` se mantiene como export
legible para backup/git (ver `export_csv`). El esquema modela el ciclo de vida
de cada anuncio:

  listings      → un anuncio único (key = "fuente:id"), con metadatos y las
                  fechas de primera / última vez visto.
  observations  → una fila por anuncio y día con su precio/km de ese día.
                  PK (key, fecha) ⇒ re-scrapear el mismo día es idempotente.

Esto da gratis: histórico de mediana por fecha, anuncios nuevos (first_seen),
bajadas de precio (observación previa) y "días en venta".

Conexión vía CELICA_DATABASE_URL (o DATABASE_URL). En docker-compose apunta al
servicio `db`; en local, a un Postgres accesible.
"""
import csv as _csv
import os
import time

import psycopg
from psycopg.rows import dict_row

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "celica_prices.csv")
DSN = (os.environ.get("CELICA_DATABASE_URL")
       or os.environ.get("DATABASE_URL")
       or "postgresql://celica:celica@localhost:5432/celica")

# Columnas del export CSV.
CSV_FIELDS = ["fecha", "fuente", "id", "precio_eur", "anio", "km", "modelo",
              "combustible", "transmision", "ciudad", "cp", "url", "foto"]


def _key(fuente, ext_id, url):
    """Identificador estable de un anuncio: la URL normalizada.

    La URL es el localizador único y estable en ambas fuentes (autoscout24 lleva
    un UUID; wallapop el id del item). NO usamos `ext_id` para la key porque el
    scraper de autoscout24 históricamente metía un dict basura idéntico en `id`
    (`{'legacyId': None, ...}`), que colapsaría todos sus anuncios en una sola
    key. Solo caemos a `ext_id` si no hay URL."""
    u = (url or "").split("?")[0].rstrip("/")
    if u:
        return f"{fuente}:{u}"
    return f"{fuente}:{(ext_id or '').strip()}"


def connect(dsn=None, retries=15, delay=2.0):
    """Conecta a Postgres reintentando mientras arranca (útil al levantar el
    contenedor `db` por primera vez)."""
    dsn = dsn or DSN
    last = None
    for i in range(retries):
        try:
            return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5)
        except psycopg.OperationalError as e:
            last = e
            if i < retries - 1:
                time.sleep(delay)
    raise last


def init(conn):
    stmts = [
        """CREATE TABLE IF NOT EXISTS listings (
            key         TEXT PRIMARY KEY,
            fuente      TEXT NOT NULL,
            ext_id      TEXT,
            url         TEXT,
            modelo      TEXT,
            anio        INTEGER,
            combustible TEXT,
            transmision TEXT,
            ciudad      TEXT,
            cp          TEXT,
            foto        TEXT,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL
        )""",
        "ALTER TABLE listings ADD COLUMN IF NOT EXISTS foto TEXT",
        """CREATE TABLE IF NOT EXISTS observations (
            key        TEXT NOT NULL REFERENCES listings(key),
            fecha      TEXT NOT NULL,
            precio_eur INTEGER,
            km         INTEGER,
            PRIMARY KEY (key, fecha)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_obs_fecha ON observations(fecha)",
        # --- Multiusuario --------------------------------------------------
        """CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'user',
            verified      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS verification_codes (
            id         SERIAL PRIMARY KEY,
            email      TEXT NOT NULL,
            code       TEXT NOT NULL,
            kind       TEXT NOT NULL DEFAULT 'verify',
            expires_at TIMESTAMPTZ NOT NULL,
            used       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        # favoritos / listas referencian el anuncio por su `fav_id` (la URL,
        # igual que el viejo localStorage). Texto suelto SIN FK a listings: así
        # un favorito sobrevive aunque el anuncio desaparezca del mercado.
        """CREATE TABLE IF NOT EXISTS favorites (
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            fav_id     TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, fav_id)
        )""",
        """CREATE TABLE IF NOT EXISTS lists (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS list_items (
            list_id    INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
            fav_id     TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (list_id, fav_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_vcodes_email ON verification_codes(email)",
    ]
    for s in stmts:
        conn.execute(s)
    conn.commit()


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def upsert_row(conn, row, fecha):
    """Inserta/actualiza un anuncio y su observación del día `fecha`.

    `row` usa las mismas claves que los scrapers / el CSV:
    fuente, id, precio_eur, anio, km, modelo, combustible, transmision,
    ciudad, cp, url.
    """
    fuente = row.get("fuente")
    key = _key(fuente, row.get("id"), row.get("url"))
    conn.execute("""
        INSERT INTO listings
            (key, fuente, ext_id, url, modelo, anio, combustible,
             transmision, ciudad, cp, foto, first_seen, last_seen)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(key) DO UPDATE SET
            url=EXCLUDED.url, modelo=EXCLUDED.modelo, anio=EXCLUDED.anio,
            combustible=EXCLUDED.combustible, transmision=EXCLUDED.transmision,
            ciudad=EXCLUDED.ciudad, cp=EXCLUDED.cp,
            foto=COALESCE(NULLIF(EXCLUDED.foto, ''), listings.foto),
            first_seen=LEAST(listings.first_seen, EXCLUDED.first_seen),
            last_seen=GREATEST(listings.last_seen, EXCLUDED.last_seen)
    """, (key, fuente, (row.get("id") or "").strip(), row.get("url"),
          row.get("modelo"), _to_int(row.get("anio")), row.get("combustible"),
          row.get("transmision"), row.get("ciudad"), row.get("cp"),
          row.get("foto"), fecha, fecha))
    conn.execute("""
        INSERT INTO observations (key, fecha, precio_eur, km)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT(key, fecha) DO UPDATE SET
            precio_eur=EXCLUDED.precio_eur, km=EXCLUDED.km
    """, (key, fecha, _to_int(row.get("precio_eur")), _to_int(row.get("km"))))


def save_rows(conn, rows, fecha):
    """Guarda una tanda de anuncios scrapeados en la fecha dada. Idempotente."""
    for r in rows:
        upsert_row(conn, r, fecha)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------- lecturas ----

def latest_date(conn):
    r = conn.execute("SELECT MAX(fecha) AS d FROM observations").fetchone()
    return r["d"] if r else None


def rows_for_date(conn, fecha):
    """Anuncios vistos en `fecha`, con el shape que esperan los consumidores
    más first_seen / last_seen para calcular nuevos y días en venta."""
    cur = conn.execute("""
        SELECT l.key, l.fuente, l.ext_id AS id, o.precio_eur, l.anio, o.km,
               l.modelo, l.combustible, l.transmision, l.ciudad, l.cp, l.url,
               l.foto, l.first_seen, l.last_seen
        FROM observations o JOIN listings l ON l.key = o.key
        WHERE o.fecha = %s
    """, (fecha,))
    return [dict(r) for r in cur.fetchall()]


def prev_price(conn, key, before_fecha):
    """Precio de la observación más reciente de `key` anterior a `before_fecha`."""
    r = conn.execute("""
        SELECT precio_eur FROM observations
        WHERE key = %s AND fecha < %s AND precio_eur IS NOT NULL
        ORDER BY fecha DESC LIMIT 1
    """, (key, before_fecha)).fetchone()
    return r["precio_eur"] if r else None


def observations_join(conn):
    """Todas las observaciones con metadatos del anuncio (para histórico/graph)."""
    cur = conn.execute("""
        SELECT o.fecha, l.fuente, l.ext_id AS id, o.precio_eur, l.anio, o.km,
               l.modelo, l.combustible, l.transmision, l.ciudad, l.cp, l.url, l.foto
        FROM observations o JOIN listings l ON l.key = o.key
        ORDER BY o.fecha, l.key
    """)
    return [dict(r) for r in cur.fetchall()]


def count(conn, table):
    if table not in ("listings", "observations"):
        raise ValueError(table)
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


# --------------------------------------------------------- export / import ----

def export_csv(conn, path=None):
    """Vuelca toda la BD al CSV legacy (backup / git)."""
    path = path or CSV_PATH
    rows = observations_join(conn)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_FIELDS})
    return len(rows)


def import_csv(conn, path=None):
    """Importa un CSV legacy a la BD (idempotente vía UPSERT)."""
    path = path or CSV_PATH
    n = 0
    with open(path, encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            fecha = r.get("fecha")
            if not fecha:
                continue
            upsert_row(conn, r, fecha)
            n += 1
    conn.commit()
    return n


def maybe_import_csv(conn, path=None):
    """Auto-migración: si la BD está vacía y hay CSV, lo importa. Devuelve nº
    filas importadas (0 si no hizo nada)."""
    path = path or CSV_PATH
    if count(conn, "observations") > 0:
        return 0
    if not os.path.exists(path):
        return 0
    return import_csv(conn, path)


# --------------------------------------------------- favoritos / listas ----

def get_favorites(conn, user_id):
    """Lista de fav_id (URLs) favoriteadas por el usuario."""
    cur = conn.execute(
        "SELECT fav_id FROM favorites WHERE user_id = %s ORDER BY created_at", (user_id,))
    return [r["fav_id"] for r in cur.fetchall()]


def add_favorite(conn, user_id, fav_id):
    conn.execute("""
        INSERT INTO favorites (user_id, fav_id) VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, fav_id))
    conn.commit()


def remove_favorite(conn, user_id, fav_id):
    conn.execute(
        "DELETE FROM favorites WHERE user_id = %s AND fav_id = %s", (user_id, fav_id))
    conn.commit()


def get_lists(conn, user_id):
    """Listas del usuario con sus items (fav_id) agregados."""
    cur = conn.execute("""
        SELECT l.id, l.name,
               COALESCE(ARRAY_AGG(li.fav_id) FILTER (WHERE li.fav_id IS NOT NULL), '{}') AS items
        FROM lists l LEFT JOIN list_items li ON li.list_id = l.id
        WHERE l.user_id = %s
        GROUP BY l.id, l.name
        ORDER BY l.created_at
    """, (user_id,))
    return [{"id": r["id"], "name": r["name"], "items": list(r["items"])}
            for r in cur.fetchall()]


def create_list(conn, user_id, name):
    r = conn.execute(
        "INSERT INTO lists (user_id, name) VALUES (%s, %s) RETURNING id",
        (user_id, name)).fetchone()
    conn.commit()
    return r["id"]


def delete_list(conn, user_id, list_id):
    """Borra la lista solo si pertenece al usuario. Devuelve filas afectadas."""
    cur = conn.execute(
        "DELETE FROM lists WHERE id = %s AND user_id = %s", (list_id, user_id))
    conn.commit()
    return cur.rowcount


def _owns_list(conn, user_id, list_id):
    return conn.execute(
        "SELECT 1 FROM lists WHERE id = %s AND user_id = %s",
        (list_id, user_id)).fetchone() is not None


def add_list_item(conn, user_id, list_id, fav_id):
    """Añade un anuncio a una lista propia. Devuelve False si no es del usuario."""
    if not _owns_list(conn, user_id, list_id):
        return False
    conn.execute("""
        INSERT INTO list_items (list_id, fav_id) VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (list_id, fav_id))
    conn.commit()
    return True


def remove_list_item(conn, user_id, list_id, fav_id):
    if not _owns_list(conn, user_id, list_id):
        return False
    conn.execute(
        "DELETE FROM list_items WHERE list_id = %s AND fav_id = %s", (list_id, fav_id))
    conn.commit()
    return True


if __name__ == "__main__":
    c = connect()
    init(c)
    print(f"DSN: {DSN}")
    print(f"listings={count(c, 'listings')} observations={count(c, 'observations')}")
