#!/bin/bash

echo "🌍 Setting up Cloudflare Tunnel..."

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "🍺 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Install cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo "📦 Installing cloudflared..."
    brew install cloudflared
else
    echo "✅ cloudflared is already installed."
fi

echo "🔑 Authenticating with Cloudflare..."
echo "A browser window will open. Please select 'app.engyne.space' (or your domain)."
cloudflared tunnel login

echo "🛠️ Creating Tunnel..."
cloudflared tunnel create engyne-mini || echo "Tunnel already exists (ignoring error)"

# Find the credentials file (it has a random UUID name)
CRED_FILE=$(find ~/.cloudflared -name "*.json" | head -n 1)
echo "🔍 Found credentials file: $CRED_FILE"

# Create config file
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: engyne-mini
credentials-file: $CRED_FILE

ingress:
  - hostname: app.engyne.space
    service: http://localhost:5173
    originRequest:
      httpHostHeader: "localhost"
  - hostname: api.engyne.space
    service: https://localhost:8001
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF

echo "📡 Routing DNS..."
cloudflared tunnel route dns engyne-mini app.engyne.space
cloudflared tunnel route dns engyne-mini api.engyne.space

echo "🚀 Starting Tunnel..."
sudo cloudflared service install
sudo cloudflared service start
echo "✅ Tunnel is live! Visit https://app.engyne.space"
