#!/bin/bash
set -e

# Determine project root dynamically
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_CONFIG="$PROJECT_ROOT/config/cloudflared.yml"

# Find the NEWEST Tunnel Credentials JSON file
# We use ls -t to sort by modification time (newest first)
TUNNEL_CRED_SRC=$(ls -tp "$HOME/.cloudflared/"*.json | grep -v /$ | head -n 1)

if [ -z "$TUNNEL_CRED_SRC" ]; then
    echo "❌ Error: No Tunnel Credentials JSON found in $HOME/.cloudflared/"
    echo "   Did you run 'cloudflared tunnel create leadforge-tunnel'?"
    exit 1
fi

# Extract UUID from filename (e.g., path/to/UUID.json -> UUID)
TUNNEL_UUID=$(basename "$TUNNEL_CRED_SRC" .json)

echo "Found newest credentials file: $TUNNEL_CRED_SRC"
echo "Tunnel UUID: $TUNNEL_UUID"

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

# 4. Update Config to point to System Credentials & UUID
# Replace the old credentials path with the new system path in the config file
echo "Updating credential path and UUID in system config..."
sudo sed -i '' "s|credentials-file: .*|credentials-file: $SYSTEM_CRED|g" "$SYSTEM_CONFIG"
sudo sed -i '' "s|tunnel: .*|tunnel: $TUNNEL_UUID|g" "$SYSTEM_CONFIG"

# 5. Fix Permissions (Root only)
echo "Securing file permissions..."
sudo chown -R root:admin "$SYSTEM_CONFIG_DIR"
sudo chmod 755 "$SYSTEM_CONFIG_DIR"
sudo chmod 600 "$SYSTEM_CONFIG"
sudo chmod 600 "$SYSTEM_CRED"

# 6. Install and Start Service
echo "Installing launchd service..."
# Note: running without arguments causes it to default to /etc/cloudflared/config.yml
# Running WITH an argument causes it to try and parse it as a token (which fails)
sudo cloudflared service install

echo "Starting service..."
# Force load if valid
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist 2>/dev/null || sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist

echo "✅ Success! Cloudflare Tunnel is now a system service."
echo "   It will auto-start on power on."
echo "   Config location: $SYSTEM_CONFIG"
