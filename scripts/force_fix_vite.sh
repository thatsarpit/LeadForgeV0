#!/bin/bash
echo "🔧 FORCE-FIXING Vite Configuration..."

# Ensure we are in the right directory
TARGET_CONFIG="dashboards/client/vite.config.js"

if [ ! -f "$TARGET_CONFIG" ]; then
    echo "❌ Error: Cannot find $TARGET_CONFIG"
    echo "Make sure you are in the LeadForgeV0 directory!"
    exit 1
fi

# Overwrite the config file directly
cat > "$TARGET_CONFIG" <<EOF
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: true,
    host: true
  },
  preview: {
    allowedHosts: true,
    host: true
  }
})
EOF

echo "✅ vite.config.js has been rewritten."
echo "📄 Content Verification:"
cat "$TARGET_CONFIG"

echo "🔄 Restarting PM2..."
pm2 delete all
pm2 start ecosystem.config.js

echo "🚀 DONE. Try refreshing https://app.engyne.space now."
