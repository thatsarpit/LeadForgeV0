#!/bin/bash
set -e

# Determine project root dynamically
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_CONFIG="$PROJECT_ROOT/config/cloudflared.yml"

# Find the Tunnel Credentials JSON file (not cert.pem)
# We look for a JSON file that looks like a UUID
TUNNEL_CRED_SRC=$(find "$HOME/.cloudflared" -name "*.json" -maxdepth 1 | head -n 1)

if [ -z "$TUNNEL_CRED_SRC" ]; then
    echo "❌ Error: No Tunnel Credentials JSON found in $HOME/.cloudflared/"
    echo "   Did you run 'cloudflared tunnel create leadforge-tunnel'?"
    exit 1
fi

echo "Found credentials file: $TUNNEL_CRED_SRC"

SYSTEM_CONFIG_DIR="/etc/cloudflared"
SYSTEM_CONFIG="$SYSTEM_CONFIG_DIR/config.yml"
SYSTEM_CRED="$SYSTEM_CONFIG_DIR/credentials.json"

echo "🛡️  Securing LeadForge Cloudflare Tunnel..."

# 1. Stop and Uninstall existing service (ignore errors if not exists)
echo "Stopping existing services..."
sudo cloudflared service uninstall || true

# 2. Prepare System Directory
echo "Creating system configuration directory..."
sudo mkdir -p "$SYSTEM_CONFIG_DIR"

# 3. Copy Configuration and Certificates
echo "Copying configuration and credentials to $SYSTEM_CONFIG_DIR..."
sudo cp "$SOURCE_CONFIG" "$SYSTEM_CONFIG"
sudo cp "$TUNNEL_CRED_SRC" "$SYSTEM_CRED"

# 4. Update Config to point to System Credentials
# Replace the old credentials path with the new system path in the config file
echo "Updating credential path in system config..."
sudo sed -i '' "s|credentials-file: .*|credentials-file: $SYSTEM_CRED|g" "$SYSTEM_CONFIG"

# 5. Fix Permissions (Root only)
echo "Securing file permissions..."
sudo chown -R root:admin "$SYSTEM_CONFIG_DIR"
sudo chmod 755 "$SYSTEM_CONFIG_DIR"
sudo chmod 600 "$SYSTEM_CONFIG"
sudo chmod 600 "$SYSTEM_CRED"

# 6. Install and Start Service
echo "Installing launchd service..."
sudo cloudflared service install "$SYSTEM_CONFIG"

echo "Starting service..."
# Force load if valid
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist 2>/dev/null || sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist

echo "✅ Success! Cloudflare Tunnel is now a system service."
echo "   It will auto-start on power on."
echo "   Config location: $SYSTEM_CONFIG"
