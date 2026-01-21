#!/bin/bash
# Generate secure secrets for LeadForge deployment

set -e

echo "🔐 LeadForge Secret Generator"
echo "================================"
echo ""

# Check for openssl
if ! command -v openssl &> /dev/null; then
    echo "❌ Error: openssl not found. Please install openssl."
    exit 1
fi

# Generate AUTH_SECRET
AUTH_SECRET=$(openssl rand -hex 32)
echo "Generated AUTH_SECRET (256-bit):"
echo "AUTH_SECRET=$AUTH_SECRET"
echo ""

# Generate DATABASE_PASSWORD
DB_PASSWORD=$(openssl rand -hex 16)
echo "Generated DATABASE_PASSWORD:"
echo "DB_PASSWORD=$DB_PASSWORD"
echo ""

# Generate JWT signing key
JWT_SECRET=$(openssl rand -hex 32)
echo "Generated JWT_SECRET (optional, separate from AUTH_SECRET):"
echo "JWT_SECRET=$JWT_SECRET"
echo ""

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file..."
    cat > .env << EOF
# Generated secrets - DO NOT COMMIT TO GIT
AUTH_SECRET=$AUTH_SECRET
DB_PASSWORD=$DB_PASSWORD

# Database URL (update host/port as needed)
# For Docker: use 'postgres' (service name)
# For local dev: use 'localhost'
DATABASE_URL=postgresql+psycopg://leadforge:$DB_PASSWORD@postgres:5432/leadforge
# DATABASE_URL=postgresql+psycopg://leadforge:$DB_PASSWORD@localhost:5432/leadforge  # Uncomment for local dev

# Application config
TOKEN_TTL_HOURS=24
NODE_ENV=production
NODE_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "local-$(date +%s)")
ADMIN_EMAIL=change_me@example.com

# CORS (comma-separated list)
ALLOWED_ORIGINS=https://app.engyne.space,https://api.engyne.space

# Optional: OAuth
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_AUTO_PROVISION=false

# Optional: Email
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
EOF
    echo "✅ Created .env file with generated secrets"
else
    echo "⚠️  .env file already exists. Add these values manually:"
    echo "   AUTH_SECRET=$AUTH_SECRET"
    echo "   DB_PASSWORD=$DB_PASSWORD"
fi

echo ""
echo "🔒 Security Notes:"
echo "   1. Never commit .env to git"
echo "   2. Use GCP Secret Manager in production"
echo "   3. Rotate secrets every 90 days"
echo "   4. AUTH_SECRET should be minimum 256 bits (64 hex chars)"
echo ""
echo "✅ Done!"
