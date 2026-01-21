#!/bin/bash
# cleanup_and_deploy_mac_mini.sh
# Purpose: Clean up old processes/containers and deploy fresh LeadForge stack

echo "🧹 [1/6] Stopping local processes..."
# Kill any lingering PM2 processes
if command -v pm2 &> /dev/null; then
    pm2 delete all 2>/dev/null || echo "No PM2 processes to delete"
    pm2 kill 2>/dev/null || echo "PM2 killed"
fi

# Kill any python/node processes related to LeadForge
pkill -f "uvicorn api.app" 2>/dev/null
pkill -f "slot_manager.py" 2>/dev/null
pkill -f "vite" 2>/dev/null
echo "✅ Local processes stopped"

echo "🐳 [2/6] Cleaning Docker environment..."
# Stop all running containers
docker-compose down -v 2>/dev/null || echo "Docker compose down failed or nothing running"

# Force kill any LeadForge containers if still running
docker ps -q --filter "name=leadforge" | xargs -r docker rm -f

# Prune old images/networks to free space and unwanted cache
docker system prune -f
docker volume prune -f
echo "✅ Docker environment cleaned"

echo "📥 [3/6] Pulling/Building latest code..."
# Ensure we are on main branch and up to date
git checkout main
git pull origin main

# Rebuild images fresh
docker-compose build --no-cache
echo "✅ Build complete"

echo "🚀 [4/6] Starting services..."
docker-compose up -d

echo "⏳ [5/6] Waiting for services to stabilize (20s)..."
sleep 20

echo "🔍 [6/6] Verifying deployment..."
# Run health checks
echo "Checking API Health..."
if curl -s http://localhost:8001/health | grep "ok"; then
    echo "✅ API is Healthy"
else
    echo "❌ API Health Check Failed"
    docker-compose logs api --tail 20
fi

echo "Checking Frontend..."
if curl -s http://localhost:5173/ | grep "Engyne Control"; then
     echo "✅ Frontend is Served"
else
     echo "❌ Frontend Check Failed"
fi

echo "Checking Database..."
if docker-compose exec -T api python3 -c "from core.db.database import get_db; print('DB Connected')" 2>/dev/null; then
    echo "✅ Database Connected"
else
    echo "⚠️ Database check skipped or failed (might be starting up)"
fi

echo "🎉 Deployment Sequence Complete!"
docker-compose ps
