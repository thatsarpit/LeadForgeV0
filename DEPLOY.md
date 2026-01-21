# Deploying LeadForgeV0 on Mac Mini

This guide assumes you have SSH access (or direct access) to the Mac Mini and the tunnel is already running to `lite.engyne.com`.

## 1. Prerequisites (Run on Mac Mini)

Ensure you have:
- **Node.js 18+**
- **Python 3.10+**
- **Docker** (for PostgreSQL)
- **PM2** (Global install)

```bash
npm install -g pm2
```

## 2. Clone the Repository

```bash
git clone https://github.com/thatsarpit/LeadForgeV0.git
cd LeadForgeV0
```

## 3. Setup Environment

1. **Python Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install "uvicorn[standard]"
   playwright install chromium
   ```

2. **Frontend Dependencies**:
   ```bash
   cd dashboards/client
   npm install
   npm run build
   cd ../..
   ```

3. **Environment Variables**:
   Copy `.env.example` to `.env` and fill it in.
   *Ensure `GOOGLE_OAUTH_REDIRECT_BASE` matches your `lite.engyne.com` URL if tunneling.*

## 4. Database Setup (Fresh Start)

Start the Postgres container:
```bash
docker run -d \
  --name leadforge-db \
  -p 5433:5432 \
  -e POSTGRES_USER=engyne \
  -e POSTGRES_PASSWORD=engyne \
  -e POSTGRES_DB=engyne_dev \
  postgres:15
```

## 5. Provision Clients

Run the helper script script to create the 3 key clients:

```bash
# Make sure venv is active
python scripts/provision_production_clients.py
```
This will:
- create the users.
- create `slots/slot01` (Voyd), `slots/slot02` (Gratitude), `slots/slot03` (Trinity).
- generate their `slot_state.json`.

## 6. Start with PM2

```bash
pm2 start ecosystem.config.js
pm2 save
```

## 7. Verify
- **API**: `http://localhost:8001/docs`
- **Frontend**: `http://localhost:5173` (Tunnel should point here)
