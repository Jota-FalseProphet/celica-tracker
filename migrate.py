#!/usr/bin/env python3
"""Migra el histórico de celica_prices.csv a la BD Postgres.

Idempotente: re-ejecutarlo no duplica nada (UPSERT). El arranque de serve.py
ya hace esto solo si la BD está vacía; este script es para migración manual o
para forzar una reimportación.
"""
import os
import db

if __name__ == "__main__":
    conn = db.connect()
    db.init(conn)
    before_obs = db.count(conn, "observations")
    if os.path.exists(db.CSV_PATH):
        n = db.import_csv(conn)
        print(f"Importadas {n} filas de {db.CSV_PATH}")
    else:
        print(f"No existe {db.CSV_PATH}, nada que importar.")
    print(f"BD {db.DSN}: "
          f"listings={db.count(conn, 'listings')} "
          f"observations={db.count(conn, 'observations')} "
          f"(antes obs={before_obs})")
