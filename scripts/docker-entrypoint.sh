#!/bin/bash
set -euo pipefail

# Set restrictive file permissions (owner-only read/write)
# Prevents other users on Mac Mini from reading sensitive slot data
umask 077

# LeadForge Docker Entrypoint Script
# Handles initialization and service routing

echo "[ENTRYPOINT] Starting LeadForge container..."
echo "[ENTRYPOINT] Service: ${1:-api}"
echo "[ENTRYPOINT] Environment: ${NODE_ENV:-development}"

# Wait for database to be ready
wait_for_db() {
    echo "[ENTRYPOINT] Waiting for database..."
    
    # Extract host from DATABASE_URL, fallback to 'postgres' (docker-compose service name)
    DB_HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:\/]*\).*/\1/p')
    DB_HOST=${DB_HOST:-postgres}
    
    until pg_isready -h "$DB_HOST" -U leadforge 2>/dev/null; do
        echo "[ENTRYPOINT] Database not ready, waiting..."
        sleep 2
    done
    echo "[ENTRYPOINT] Database is ready!"
}

# Run database migrations
run_migrations() {
    echo "[ENTRYPOINT] Running database migrations..."
    cd /app
    
    # Run Alembic migrations (handles both Postgres and SQLite if configured, but critical for Postgres)
    if command -v alembic &> /dev/null; then
        echo "[ENTRYPOINT] Running Alembic upgrade head..."
        if ! alembic upgrade head; then
            echo "[ENTRYPOINT] ❌ Alembic migration failed! Exiting..."
            exit 1
        fi
    else
        echo "[ENTRYPOINT] Alembic not found, falling back to legacy init_db..."
        # Initialize leads table if needed - fail fast on errors
        if ! python3 -c "from core.db.database import init_db; init_db()"; then
            echo "[ENTRYPOINT] ❌ Migration failed! Exiting..."
            exit 1
        fi
    fi
    echo "[ENTRYPOINT] Migrations complete"
}

# Trap SIGTERM for graceful shutdown
trap 'echo "[ENTRYPOINT] Received SIGTERM, shutting down gracefully..."; exit 0' SIGTERM

# Service routing
case "${1:-api}" in
    api)
        echo "[ENTRYPOINT] Starting API service..."
        wait_for_db
        run_migrations
        cd /app
        exec uvicorn api.app:app \
            --host 0.0.0.0 \
            --port 8001 \
            --log-level info \
            --no-access-log
        ;;
    
    manager)
        echo "[ENTRYPOINT] Starting Slot Manager..."
        wait_for_db
        sleep 5  # Wait for API to be ready
        cd /app
        exec python3 core/engine/slot_manager.py
        ;;
    
    frontend)
        echo "[ENTRYPOINT] Starting Frontend..."
        cd /app/dashboards/client/dist
        if [ -f "index.html" ]; then
            echo "[ENTRYPOINT] Serving SPA on port 5173..."
            exec python3 /app/scripts/spa_server.py
        else
            echo "[ENTRYPOINT] ❌ Frontend index.html not found!"
            exit 1
        fi
        ;;
    
    worker)
        # For future worker-specific containers
        echo "[ENTRYPOINT] Starting Worker..."
        wait_for_db
        shift  # Remove 'worker' from $@
        exec python3 -m core.workers.indiamart_worker "$@"
        ;;
    
    *)
        echo "[ENTRYPOINT] Unknown service: $1"
        echo "Usage: $0 {api|manager|frontend|worker}"
        exit 1
        ;;
esac
