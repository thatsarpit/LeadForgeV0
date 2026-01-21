# Postgres Migration & Cleanup

Use this on each machine to move from `config/users.yml` to Postgres and remove test clients.

## 1) Prepare allowlist/denylist (production)

Create one of these locally (ignored by git):

- `config/clients.allowlist.txt` (only these emails will be kept)
- `config/clients.denylist.txt` (these emails will be removed)

## 2) Run migrations

```bash
alembic upgrade head
```

## 3) Migrate users and prune test slots

Allowlist approach (recommended for production):

```bash
python3 scripts/migrate_users_to_db.py \
  --apply \
  --reset \
  --update-existing \
  --allowlist config/clients.allowlist.txt \
  --seed-allowlist \
  --prune-slots
```

Denylist approach (if you only want to drop a few known test emails):

```bash
python3 scripts/migrate_users_to_db.py \
  --apply \
  --reset \
  --update-existing \
  --denylist config/clients.denylist.txt \
  --prune-slots
```

## Notes

- `--reset` wipes existing DB users and slots before import.
- `--prune-slots` deletes slot directories that belong only to skipped users.
- Use allowlist on production to guarantee no test users remain.

## Demo code generation (Linux)

Generate 10 demo codes tied to `slot_001` through `slot_010`:

```bash
python3 scripts/generate_demo_codes.py --count 10
```

Rotate codes if needed:

```bash
python3 scripts/generate_demo_codes.py --count 10 --rotate
```

## Import fixed demo codes (Linux)

If you want the Linux demo to use a pre-generated set of codes, create `config/demo_codes.csv`
and run:

```bash
python3 scripts/import_demo_codes.py --apply --rotate --file config/demo_codes.csv
```
