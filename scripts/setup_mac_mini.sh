#!/bin/bash
set -e

# LeadForgeV0 Auto-Deployment Script for Mac Mini

echo "🚀 Starting LeadForgeV0 Deployment..."

# 1. System Checks
echo "🔍 Checking System Dependencies..."
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew not found. Please install it first."
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "📦 Installing Node.js..."
    brew install node@18
fi

if ! command -v python3 &> /dev/null; then
    echo "📦 Installing Python..."
    brew install python@3.10
fi

if ! command -v docker &> /dev/null; then
    echo "⚠️ Docker not found. Please install Docker Desktop for Mac manually."
    # We continue, assuming the user might fix it or it's in a path we missed
fi

if ! command -v pm2 &> /dev/null; then
    echo "📦 Installing PM2..."
    npm install -g pm2
fi

# 2. Project Setup
echo "📂 Setting up Project..."
# Check if we are in the repo, if not clone it
if [ ! -d ".git" ]; then
    if [ -d "LeadForgeV0" ]; then
        cd LeadForgeV0
    else
        echo "📥 Cloning Repository..."
        git clone https://github.com/thatsarpit/LeadForgeV0.git
        cd LeadForgeV0
    fi
else
    echo "🔄 Pulling latest changes..."
    git pull origin main
fi

# 3. Backend Setup
echo "🐍 Setting up Python Environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
pip install "uvicorn[standard]"
echo "🎭 Installing Playwright Browsers..."
playwright install chromium

# 4. Frontend Setup
echo "🎨 Building Frontend..."
cd dashboards/client
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run build
cd ../..

# 5. Database Setup
echo "🗄️  Setting up Database..."
if docker ps -a | grep -q leadforge-db; then
    echo "✅ Database container exists."
    if ! docker ps | grep -q leadforge-db; then
        echo "🚀 Starting existing database container..."
        docker start leadforge-db
    fi
else
    echo "🚀 Creating new database container..."
    docker run -d \
      --name leadforge-db \
      -p 5433:5432 \
      -e POSTGRES_USER=engyne \
      -e POSTGRES_PASSWORD=engyne \
      -e POSTGRES_DB=engyne_dev \
      postgres:15
    echo "⏳ Waiting for DB to be ready..."
    sleep 10
fi

# 6. Run Migrations / Provisioning
echo "🏗️  Provisioning Clients..."
python scripts/provision_production_clients.py

# 7. Start Services
echo "🚀 Starting Services with PM2..."
pm2 start ecosystem.config.js
pm2 save

echo "=========================================="
echo "✅ Deployment Complete!"
echo "📡 API: http://localhost:8001"
echo "🎨 Frontend: http://localhost:5173"
echo "=========================================="
