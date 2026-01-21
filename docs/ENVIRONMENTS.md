# Environments

This project now uses Postgres as the source of truth. Each machine must have its own isolated database and `.env` file.

## Required environment variables

- `DATABASE_URL` (SQLAlchemy format, e.g. `postgresql+psycopg://user:pass@localhost:5432/engyne`)
- `AUTH_SECRET` (JWT signing secret)
- `ADMIN_EMAIL` (admin account email, default is `thatsarpitg@gmail.com`)
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_BASE` (base URL of the API, used by Google OAuth)
- `GOOGLE_OAUTH_ALLOWED_DOMAINS` (optional, comma-separated)
- `GOOGLE_OAUTH_ALLOWED_REDIRECTS` (optional, comma-separated)
- `GOOGLE_OAUTH_AUTO_PROVISION` (default `false`)
- `DEMO_LOGIN_ENABLED` (default `false`)
- `DEMO_LOGIN_DOMAIN` (default `demo.local`)
- `REMOTE_LOGIN_ENABLED` (enable browser-based login sessions on nodes)
- `REMOTE_LOGIN_TIMEOUT_MINUTES` (default `15`)
- `REMOTE_LOGIN_PUBLIC_BASE` (public base URL for websocket streaming)
- `REMOTE_LOGIN_VIEWPORT_WIDTH` / `REMOTE_LOGIN_VIEWPORT_HEIGHT`

## Mac mini (production source of truth)

- Use a dedicated Postgres database on the Mac mini.
- Keep `GOOGLE_OAUTH_AUTO_PROVISION=false`.
- Admin email should be `thatsarpitg@gmail.com`.
- Run migrations before starting the API.
- This DB is the only production source of truth.
- Remote login requires Playwright installed in the API venv and Chromium downloaded.

## Linux PC (demo)

- Use a separate Postgres database.
- Seed with a sanitized snapshot of production when needed.
- Keep credentials and OAuth redirect URL distinct from production.
- Set `DEMO_LOGIN_ENABLED=true` for demo code access.
- In `dashboards/client/.env`, set `VITE_DEMO_LOGIN_ENABLED=true` to show the demo login box.

## MacBook (development)

- Use a local Postgres database (or Docker) that never connects to production.
- Use local OAuth redirect URLs only.
- Safe place to run migrations and schema changes first.

## Migration workflow

1. Run Alembic migrations on the target machine.
2. Run `scripts/migrate_users_to_db.py --apply` to import legacy users.
3. If needed, prune old test clients with an allowlist or denylist.
