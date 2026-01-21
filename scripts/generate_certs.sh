#!/bin/bash
# scripts/generate_certs.sh

echo "🔒 Generating Self-Signed SSL Certificates..."

# Create certs directory if it doesn't exist
mkdir -p certs

# Generate Key and Certificate (valid for 365 days)
# CN=*.engyne.space allows it to work for app.engyne.space and hosts file overrides
openssl req -x509 -newkey rsa:2048 -keyout certs/server.key -out certs/server.crt -days 365 -nodes -subj "/C=US/ST=State/L=City/O=Engyne/CN=*.engyne.space"

echo "✅ Certificates generated in ./certs/"
echo "   - certs/server.key"
echo "   - certs/server.crt"
