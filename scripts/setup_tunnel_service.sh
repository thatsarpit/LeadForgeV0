#!/bin/bash
set -e

# Determine project root dynamically
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_CONFIG="$PROJECT_ROOT/config/cloudflared.yml"
# We assume the cert is always in the user's home dir default location which is standard
SOURCE_CERT="$HOME/.cloudflared/cert.pem"
SYSTEM_CONFIG_DIR="/etc/cloudflared"
SYSTEM_CONFIG="$SYSTEM_CONFIG_DIR/config.yml"
SYSTEM_CERT="$SYSTEM_CONFIG_DIR/cert.pem"

echo "🛡️  Securing LeadForge Cloudflare Tunnel..."

# 1. Stop and Uninstall existing service (ignore errors if not exists)
echo "Stopping existing services..."
sudo cloudflared service uninstall || true

# 2. Prepare System Directory
echo "Creating system configuration directory..."
sudo mkdir -p "$SYSTEM_CONFIG_DIR"

# 3. Copy Configuration and Certificates
echo "Copying configuration and certificates to $SYSTEM_CONFIG_DIR..."
sudo cp "$SOURCE_CONFIG" "$SYSTEM_CONFIG"
sudo cp "$SOURCE_CERT" "$SYSTEM_CERT"

# 4. Update Config to point to System Cert
# Replace the old user path with the new system path in the config file
echo "Updating credential path in system config..."
sudo sed -i '' "s|credentials-file: .*|credentials-file: $SYSTEM_CERT|g" "$SYSTEM_CONFIG"

# 5. Fix Permissions (Root only)
echo "Securing file permissions..."
sudo chown -R root:admin "$SYSTEM_CONFIG_DIR"
sudo chmod 755 "$SYSTEM_CONFIG_DIR"
sudo chmod 600 "$SYSTEM_CONFIG"
sudo chmod 600 "$SYSTEM_CERT"

# 6. Install and Start Service
echo "Installing launchd service..."
sudo cloudflared service install "$SYSTEM_CONFIG"

echo "Starting service..."
# Force load if valid
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist 2>/dev/null || sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist

echo "✅ Success! Cloudflare Tunnel is now a system service."
echo "   It will auto-start on power on."
echo "   Config location: $SYSTEM_CONFIG"
