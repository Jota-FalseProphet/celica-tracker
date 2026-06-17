#!/usr/bin/env python3
"""Autenticación del celica-tracker: registro/login con email+contraseña.

Postgres como almacén (reutiliza db.connect, psycopg3). Contraseñas con PBKDF2.
Verificación de email obligatoria y reset de contraseña, ambos por código de 6
dígitos enviado con email_send. Sesiones por token en tabla `sessions`
(la cookie httponly la gestiona app.py).

El rol vive en users.role ('user' | 'admin'). Se asciende a admin a mano:
  UPDATE users SET role='admin' WHERE email='tu@correo';
"""
import hashlib
import hmac
import os
import random
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

import db

CODE_EXPIRY_MIN = 10
MIN_PASSWORD_LEN = 8


def _conn():
    return db.connect()


def _hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split(":")
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(key.hex(), key_hex)


def _norm(email: str) -> str:
    return (email or "").lower().strip()


# ------------------------------------------------------------- registro ----

def register(email: str, password: str) -> dict:
    email = _norm(email)
    if "@" not in email or "." not in email:
        return {"ok": False, "error": "Email no válido"}
    if len(password or "") < MIN_PASSWORD_LEN:
        return {"ok": False, "error": f"La contraseña necesita ≥{MIN_PASSWORD_LEN} caracteres"}
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            (email, _hash_password(password)))
        conn.commit()
        return {"ok": True}
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        return {"ok": False, "error": "Ese email ya está registrado"}
    finally:
        conn.close()


def login(email: str, password: str) -> dict:
    email = _norm(email)
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, role, verified FROM users WHERE email = %s",
            (email,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return {"ok": False, "error": "Email o contraseña incorrectos"}
        if not row["verified"]:
            return {"ok": False, "error": "Cuenta sin verificar. Revisa tu correo.", "unverified": True}
        token = secrets.token_urlsafe(48)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s)",
                     (token, row["id"]))
        conn.commit()
        return {"ok": True, "token": token,
                "user": {"id": row["id"], "email": row["email"], "role": row["role"]}}
    finally:
        conn.close()


def logout(token: str):
    conn = _conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
    finally:
        conn.close()


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    conn = _conn()
    try:
        row = conn.execute("""
            SELECT u.id, u.email, u.role
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = %s
        """, (token,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# -------------------------------------------------- códigos / verificación ----

def _new_code(conn, email: str, kind: str) -> str:
    conn.execute(
        "UPDATE verification_codes SET used = TRUE WHERE email = %s AND kind = %s AND used = FALSE",
        (email, kind))
    code = f"{random.randint(0, 999999):06d}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MIN)
    conn.execute(
        "INSERT INTO verification_codes (email, code, kind, expires_at) VALUES (%s, %s, %s, %s)",
        (email, code, kind, expires))
    conn.commit()
    return code


def create_verification_code(email: str) -> str:
    conn = _conn()
    try:
        return _new_code(conn, _norm(email), "verify")
    finally:
        conn.close()


def create_reset_code(email: str) -> str | None:
    """Genera código de reset solo si el email existe (devuelve None si no, para
    no filtrar qué correos están registrados)."""
    email = _norm(email)
    conn = _conn()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            return None
        return _new_code(conn, email, "reset")
    finally:
        conn.close()


def _consume_code(conn, email: str, code: str, kind: str) -> dict:
    row = conn.execute("""
        SELECT id, expires_at FROM verification_codes
        WHERE email = %s AND code = %s AND kind = %s AND used = FALSE
        ORDER BY created_at DESC LIMIT 1
    """, (email, (code or "").strip(), kind)).fetchone()
    if not row:
        return {"ok": False, "error": "Código incorrecto"}
    if row["expires_at"] < datetime.now(timezone.utc):
        return {"ok": False, "error": "Código caducado. Pide uno nuevo."}
    conn.execute("UPDATE verification_codes SET used = TRUE WHERE id = %s", (row["id"],))
    return {"ok": True}


def verify_code(email: str, code: str) -> dict:
    email = _norm(email)
    conn = _conn()
    try:
        res = _consume_code(conn, email, code, "verify")
        if res["ok"]:
            conn.execute("UPDATE users SET verified = TRUE WHERE email = %s", (email,))
        conn.commit()
        return res
    finally:
        conn.close()


# ------------------------------------------------------- admin: usuarios ----

def _admin_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'").fetchone()["n"]


def list_users() -> list:
    """Todos los usuarios con conteo de favoritos y listas (para el panel admin)."""
    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT u.id, u.email, u.role, u.verified, u.created_at,
                   (SELECT COUNT(*) FROM favorites f WHERE f.user_id = u.id) AS n_fav,
                   (SELECT COUNT(*) FROM lists l WHERE l.user_id = u.id) AS n_lists
            FROM users u ORDER BY u.created_at
        """)
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["verified"] = bool(d["verified"])
            out.append(d)
        return out
    finally:
        conn.close()


def admin_set_password(user_id: int, new_password: str) -> dict:
    if len(new_password or "") < MIN_PASSWORD_LEN:
        return {"ok": False, "error": f"La contraseña necesita ≥{MIN_PASSWORD_LEN} caracteres"}
    conn = _conn()
    try:
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                     (_hash_password(new_password), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))  # fuerza re-login
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def admin_set_email(user_id: int, email: str) -> dict:
    email = _norm(email)
    if "@" not in email or "." not in email:
        return {"ok": False, "error": "Email no válido"}
    conn = _conn()
    try:
        conn.execute("UPDATE users SET email = %s WHERE id = %s", (email, user_id))
        conn.commit()
        return {"ok": True}
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        return {"ok": False, "error": "Ese email ya está en uso"}
    finally:
        conn.close()


def admin_set_role(user_id: int, role: str) -> dict:
    if role not in ("user", "admin"):
        return {"ok": False, "error": "Rol inválido"}
    conn = _conn()
    try:
        cur = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
        if cur and cur["role"] == "admin" and role != "admin" and _admin_count(conn) <= 1:
            return {"ok": False, "error": "No puedes quitar el último admin"}
        conn.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def admin_set_verified(user_id: int, verified: bool) -> dict:
    conn = _conn()
    try:
        conn.execute("UPDATE users SET verified = %s WHERE id = %s", (bool(verified), user_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def admin_delete_user(user_id: int) -> dict:
    conn = _conn()
    try:
        cur = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
        if not cur:
            return {"ok": False, "error": "Usuario no encontrado"}
        if cur["role"] == "admin" and _admin_count(conn) <= 1:
            return {"ok": False, "error": "No puedes borrar el último admin"}
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))  # cascade: favs/lists/sesiones
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def admin_create_user(email: str, password: str, role: str = "user") -> dict:
    res = register(email, password)
    if not res["ok"]:
        return res
    conn = _conn()
    try:
        conn.execute("UPDATE users SET verified = TRUE, role = %s WHERE email = %s",
                     (role if role in ("user", "admin") else "user", _norm(email)))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def reset_password(email: str, code: str, new_password: str) -> dict:
    email = _norm(email)
    if len(new_password or "") < MIN_PASSWORD_LEN:
        return {"ok": False, "error": f"La contraseña necesita ≥{MIN_PASSWORD_LEN} caracteres"}
    conn = _conn()
    try:
        res = _consume_code(conn, email, code, "reset")
        if res["ok"]:
            conn.execute("UPDATE users SET password_hash = %s WHERE email = %s",
                         (_hash_password(new_password), email))
            # invalida sesiones abiertas tras cambiar contraseña
            conn.execute("""
                DELETE FROM sessions WHERE user_id =
                    (SELECT id FROM users WHERE email = %s)
            """, (email,))
        conn.commit()
        return res
    finally:
        conn.close()
