#!/usr/bin/env python3
"""celica-tracker · servidor FastAPI.

Sirve el dashboard estático y expone la API multiusuario:

  Público:
    GET  /                      → dashboard.html
    GET  /api/status            → estado del scrape + próximo auto-scrape
    POST /api/register · /api/verify · /api/login · /api/logout
    POST /api/resend  · /api/reset/request · /api/reset/confirm
    GET  /api/me                → usuario de la sesión (o null)

  Requiere sesión:
    GET/POST/DELETE  /api/favorites
    GET/POST  /api/lists  · DELETE /api/lists/{id}
    POST/DELETE  /api/lists/{id}/items

  Requiere admin:
    POST /api/scrape           → fuerza un scrape manual (auto-scrape sigue solo)

Auth por cookie httponly `celica_session`. El auto-scrape en background corre
igual, sea quien sea (o nadie) quien visite la web.
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import auth
import db
import email_send
import scrape_runner

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_COOKIE = "celica_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 días
SECURE_COOKIES = os.environ.get("CELICA_SECURE_COOKIES", "1").lower() not in ("0", "false", "no", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        conn = db.connect()
        db.init(conn)
        db.maybe_import_csv(conn)
        print(f"BD lista: listings={db.count(conn,'listings')} "
              f"observations={db.count(conn,'observations')}", flush=True)
        conn.close()
    except Exception as e:
        print(f"⚠ No se pudo inicializar la BD: {e}", flush=True)
    if scrape_runner.start_scheduler():
        print(f"auto-scrape activado (media ~2h, silencio "
              f"{scrape_runner.QUIET_START:02d}:00–{scrape_runner.QUIET_END:02d}:00)", flush=True)
    yield


app = FastAPI(title="celica-tracker", lifespan=lifespan)


# ----------------------------------------------------------- dependencias ----

def current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    return auth.user_for_token(token)


def require_user(request: Request):
    user = current_user(request)
    if not user:
        return None
    return user


def _need_login():
    return JSONResponse({"error": "Inicia sesión"}, status_code=401)


def _forbid():
    return JSONResponse({"error": "Solo el admin puede hacer esto"}, status_code=403)


def require_admin(request: Request):
    """Devuelve (user, None) si es admin, o (None, respuesta_error)."""
    user = current_user(request)
    if not user:
        return None, _need_login()
    if user["role"] != "admin":
        return None, _forbid()
    return user, None


# ---------------------------------------------------------------- estáticos --

def _file(name, media):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return _file("dashboard.html", "text/html")


@app.get("/dashboard.html")
def dashboard():
    return _file("dashboard.html", "text/html")


@app.get("/scene.js")
def scene_js():
    return _file("scene.js", "text/javascript")


@app.get("/three.module.js")
def three_js():
    return _file("three.module.js", "text/javascript")


@app.get("/celica_market.png")
def market_png():
    return _file("celica_market.png", "image/png")


# ------------------------------------------------------------------ status ---

@app.get("/api/status")
def status():
    return scrape_runner.snapshot()


@app.get("/api/me")
def me(request: Request):
    return {"user": current_user(request)}


# -------------------------------------------------------------------- auth ---

class Credentials(BaseModel):
    email: str
    password: str


class CodeIn(BaseModel):
    email: str
    code: str


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    email: str
    code: str
    password: str


@app.post("/api/register")
def register(body: Credentials):
    res = auth.register(body.email, body.password)
    if not res["ok"]:
        return JSONResponse(res, status_code=400)
    _send_verification(body.email)
    return {"ok": True, "next": "verify"}


def _send_verification(email):
    code = auth.create_verification_code(email)
    try:
        email_send.send_verification_email(email.lower().strip(), code)
    except Exception as e:
        print(f"⚠ fallo enviando verificación a {email}: {e}", flush=True)


@app.post("/api/resend")
def resend(body: EmailIn):
    _send_verification(body.email)
    return {"ok": True}


@app.post("/api/verify")
def verify(body: CodeIn):
    res = auth.verify_code(body.email, body.code)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/login")
def login(body: Credentials, response: Response):
    res = auth.login(body.email, body.password)
    if not res["ok"]:
        return JSONResponse(res, status_code=401)
    response.set_cookie(
        SESSION_COOKIE, res["token"], max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="lax", secure=SECURE_COOKIES, path="/")
    return {"ok": True, "user": res["user"]}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/reset/request")
def reset_request(body: EmailIn):
    code = auth.create_reset_code(body.email)
    if code:
        try:
            email_send.send_reset_email(body.email.lower().strip(), code)
        except Exception as e:
            print(f"⚠ fallo enviando reset a {body.email}: {e}", flush=True)
    # Respuesta idéntica exista o no el email (no filtrar registrados)
    return {"ok": True}


@app.post("/api/reset/confirm")
def reset_confirm(body: ResetIn):
    res = auth.reset_password(body.email, body.code, body.password)
    return res if res["ok"] else JSONResponse(res, status_code=400)


# ------------------------------------------------------------- favoritos -----

class FavIn(BaseModel):
    fav_id: str


@app.get("/api/favorites")
def favorites_get(request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        return {"favorites": db.get_favorites(conn, user["id"])}
    finally:
        conn.close()


@app.post("/api/favorites")
def favorites_add(body: FavIn, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        db.add_favorite(conn, user["id"], body.fav_id)
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/favorites")
def favorites_del(body: FavIn, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        db.remove_favorite(conn, user["id"], body.fav_id)
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- listas -----

class ListIn(BaseModel):
    name: str


@app.get("/api/lists")
def lists_get(request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        return {"lists": db.get_lists(conn, user["id"])}
    finally:
        conn.close()


@app.post("/api/lists")
def lists_create(body: ListIn, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    name = (body.name or "").strip()
    if not name:
        return JSONResponse({"error": "Nombre vacío"}, status_code=400)
    conn = db.connect()
    try:
        lid = db.create_list(conn, user["id"], name[:80])
        return {"ok": True, "id": lid}
    finally:
        conn.close()


@app.delete("/api/lists/{list_id}")
def lists_delete(list_id: int, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        db.delete_list(conn, user["id"], list_id)
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/lists/{list_id}/items")
def list_item_add(list_id: int, body: FavIn, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        if not db.add_list_item(conn, user["id"], list_id, body.fav_id):
            return JSONResponse({"error": "Lista no encontrada"}, status_code=404)
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/lists/{list_id}/items")
def list_item_del(list_id: int, body: FavIn, request: Request):
    user = require_user(request)
    if not user:
        return _need_login()
    conn = db.connect()
    try:
        if not db.remove_list_item(conn, user["id"], list_id, body.fav_id):
            return JSONResponse({"error": "Lista no encontrada"}, status_code=404)
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- scrape -----

# ----------------------------------------------------- admin: usuarios -------

class PwdIn(BaseModel):
    password: str


class EmailUpd(BaseModel):
    email: str


class RoleIn(BaseModel):
    role: str


class VerIn(BaseModel):
    verified: bool


class NewUserIn(BaseModel):
    email: str
    password: str
    role: str = "user"


def _admin_or_error(request: Request):
    return require_admin(request)


@app.get("/api/admin/users")
def admin_users(request: Request):
    user, err = require_admin(request)
    if err:
        return err
    return {"users": auth.list_users()}


@app.post("/api/admin/users")
def admin_create(body: NewUserIn, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    res = auth.admin_create_user(body.email, body.password, body.role)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/admin/users/{user_id}/password")
def admin_password(user_id: int, body: PwdIn, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    res = auth.admin_set_password(user_id, body.password)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/admin/users/{user_id}/email")
def admin_email(user_id: int, body: EmailUpd, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    res = auth.admin_set_email(user_id, body.email)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/admin/users/{user_id}/role")
def admin_role(user_id: int, body: RoleIn, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    res = auth.admin_set_role(user_id, body.role)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/admin/users/{user_id}/verified")
def admin_verified(user_id: int, body: VerIn, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    res = auth.admin_set_verified(user_id, body.verified)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.delete("/api/admin/users/{user_id}")
def admin_delete(user_id: int, request: Request):
    user, err = require_admin(request)
    if err:
        return err
    if user["id"] == user_id:
        return JSONResponse({"error": "No puedes borrarte a ti mismo"}, status_code=400)
    res = auth.admin_delete_user(user_id)
    return res if res["ok"] else JSONResponse(res, status_code=400)


@app.post("/api/scrape")
def scrape(request: Request):
    user = current_user(request)
    if not user:
        return _need_login()
    if user["role"] != "admin":
        return JSONResponse({"error": "Solo el admin puede forzar el scrape"}, status_code=403)
    if not scrape_runner.start_scrape_async(trigger="manual"):
        return JSONResponse({"error": "Ya hay un scrape en marcha"}, status_code=409)
    return JSONResponse({"started": True}, status_code=202)
