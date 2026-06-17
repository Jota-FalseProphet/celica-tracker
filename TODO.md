# TODO · celica-tracker

## Multiusuario (nivel 1 — ✅ IMPLEMENTADO)

El dashboard ya es multiusuario. Backend migrado a **FastAPI** (`app.py`,
`uvicorn app:app`). Auth por cookie httponly, PBKDF2, verificación de email y
reset de contraseña vía **Resend** (`email_send.py`, transporte enchufable a SMTP
para el mailserver propio). El reto de generalizar el scraping (nivel 3) sigue
pendiente; ver abajo.

### Requisitos fijados — hechos
- [x] **Cuentas de usuario**: registro/login, PBKDF2, sesiones por cookie
      httponly + tabla `sessions`. Verificación de email + reset de contraseña.
- [x] **Roles** `admin`/`user` (columna `users.role`). Admin se asciende a mano:
      `UPDATE users SET role='admin' WHERE email='…'`.
- [x] **Botón "Refrescar ahora" solo admin**: `POST /api/scrape` → 401 anon /
      403 user; el botón solo se muestra a admin. Auto-scrape en background intacto.
- [x] **Favoritos por usuario** en BD (`favorites`), sincronizados; invitado sigue
      usando `localStorage`.
- [x] **Listas nombradas** por usuario (`lists`/`list_items`) + filtro por lista.
- [x] **Panel admin** de gestión de usuarios (listar/crear/editar email/cambiar
      contraseña/rol/verificado/borrar) en `/api/admin/*`, solo admin.

### Refactor transversal (necesario a cualquier nivel)
- [ ] Migrar `serve.py` (http.server de stdlib) → **FastAPI** (mismo stack que
      Sefer/Magi). Auth, middleware de rol, render por usuario o API+JS.
      El dashboard hoy es HTML estático generado; multiusuario pide vista por
      usuario → render dinámico (Jinja o API+frontend).
- [ ] Postgres ya está; reutilizar `db.py`. Posible Redis para sesiones/cola.
- [ ] Tabla `users(id, email, pass_hash, role, created_at)` + `favorites(user_id, listing_key)`.

### Niveles de alcance (estimación solo-dev)
1. **Ligero (~1 día)**: cuentas + roles + favoritos sincronizados + botón
   refrescar solo-admin. Todos ven el mismo mercado Celica.
2. **Medio (~3-5 días)**: + búsquedas guardadas por usuario (filtros precio/km/año
   sobre los datos ya scrapeados) + alertas (email/push) por chollo/bajada.
3. **Completo (~2-4 semanas)**: cada usuario rastrea cualquier marca/modelo →
   generalizar scrapers a queries arbitrarias, cola de jobs + scheduler por
   búsqueda, **dedup** de búsquedas solapadas y **rate-limiting global anti-ban**
   (probablemente proxies residenciales, coste recurrente). Aquí está el 80% del
   coste y del riesgo.

Recomendación: empezar por el **nivel 1** (incluye ya roles + admin-only refresh),
y subir a nivel 2 si se quiere. El nivel 3 solo si se busca convertirlo en producto.
