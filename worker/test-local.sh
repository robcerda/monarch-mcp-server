#!/bin/bash

# Quick test script for local Monarch MCP server
# Run this to verify everything works before deploying

echo "🧪 Monarch MCP Server - Local Test Script"
echo "=========================================="
echo ""

# Check if wrangler is installed
if ! command -v wrangler &> /dev/null; then
    echo "❌ Wrangler not found. Install with: npm install -g wrangler"
    exit 1
fi

# Check if .dev.vars exists
if [ ! -f .dev.vars ]; then
    echo "⚠️  .dev.vars not found. Creating from template..."
    cp .dev.vars.example .dev.vars
    echo "📝 Please edit .dev.vars with your credentials and run this script again."
    exit 1
fi

# Check if dependencies are installed
if [ ! -d node_modules ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

echo "✅ Prerequisites check passed"
echo ""

# Start dev server in background
echo "🚀 Starting local dev server..."
npx wrangler dev &
WRANGLER_PID=$!

# Wait for server to start
echo "⏳ Waiting for server to start..."
sleep 5

# Test health endpoint
echo ""
echo "1️⃣ Testing health endpoint..."
HEALTH=$(curl -s http://localhost:8787/health)
if echo "$HEALTH" | grep -q "ok"; then
    echo "   ✅ Health check passed"
    echo "   Response: $HEALTH"
else
    echo "   ❌ Health check failed"
    echo "   Response: $HEALTH"
    kill $WRANGLER_PID 2>/dev/null
    exit 1
fi

# Test home page
echo ""
echo "2️⃣ Testing home page..."
HOME_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8787/)
if [ "$HOME_RESPONSE" = "200" ]; then
    echo "   ✅ Home page accessible (HTTP $HOME_RESPONSE)"
else
    echo "   ❌ Home page failed (HTTP $HOME_RESPONSE)"
    kill $WRANGLER_PID 2>/dev/null
    exit 1
fi

# Test MCP endpoint (should require auth)
echo ""
echo "3️⃣ Testing MCP endpoint..."
MCP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8787/mcp)
if [ "$MCP_RESPONSE" = "302" ] || [ "$MCP_RESPONSE" = "401" ]; then
    echo "   ✅ MCP endpoint protected (HTTP $MCP_RESPONSE - requires auth)"
else
    echo "   ⚠️  MCP endpoint returned HTTP $MCP_RESPONSE"
fi

echo ""
echo "=========================================="
echo "✅ All basic tests passed!"
echo ""
echo "📋 Next steps:"
echo ""
echo "1. Open browser to: http://localhost:8787"
echo "2. Click 'Login with GitHub' to test OAuth"
echo "3. Visit: http://localhost:8787/auth/refresh to test token storage"
echo "4. Use Cloudflare Tunnel to test with ChatGPT:"
echo "   cloudflared tunnel --url http://localhost:8787"
echo ""
echo "🛑 Press Ctrl+C to stop the dev server"
echo ""

# Keep wrangler running in foreground
wait $WRANGLER_PID
