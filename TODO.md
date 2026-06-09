# TODO · celica-tracker

## Multiusuario (planificado — NO implementado)

Objetivo: convertir el dashboard (hoy single-shared, sin cuentas) en multiusuario
"bien". El reto real no es el login, es generalizar el scraping sin que nos
baneen. Ver discusión de niveles abajo.

### Requisitos fijados
- [ ] **Cuentas de usuario**: registro/login, hash de contraseñas (passlib),
      sesiones (cookies seguras) o JWT.
- [ ] **Roles**: al menos `admin` y `user`. Debe existir **un admin**.
- [ ] **Botón "Refrescar ahora" solo para admin**: el scrape manual
      (`POST /api/scrape`) debe estar **protegido por auth y restringido al rol
      admin**. Para `user` el botón se oculta/deshabilita y el endpoint devuelve
      403. El **auto-scrape en background sigue corriendo igual** (es del
      servidor, no depende del usuario).
- [ ] **Favoritos por usuario**: mover de `localStorage` → BD (tabla por usuario),
      sincronizados entre dispositivos.

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
