# 🚀 Deployment Guide: Monarch Money Remote MCP Server

This guide walks you through deploying your Monarch Money MCP server to Cloudflare Workers.

## 📋 Prerequisites

✅ Cloudflare account (free tier works)
✅ GitHub OAuth apps created (development & production)
✅ Node.js and npm installed
✅ Wrangler CLI installed (`npm install -g wrangler`)

---

## 🔑 Step 1: Authenticate Wrangler

```bash
cd worker
npx wrangler login
```

This will open a browser window to authenticate with Cloudflare.

---

## 🗄️ Step 2: Create KV Namespaces

Create two KV namespaces for storing OAuth sessions and Monarch tokens:

```bash
# Create OAuth KV namespace
npx wrangler kv namespace create "OAUTH_KV"

# Create Monarch KV namespace
npx wrangler kv namespace create "MONARCH_KV"
```

**Important:** Copy the namespace IDs from the output. They look like this:
```
{ binding = "OAUTH_KV", id = "abc123def456..." }
{ binding = "MONARCH_KV", id = "xyz789uvw012..." }
```

---

## ⚙️ Step 3: Update wrangler.jsonc

Edit `worker/wrangler.jsonc` and replace the placeholder KV IDs:

```jsonc
{
  "name": "monarch-mcp",
  // ... other config ...
  "kv_namespaces": [
    {
      "binding": "OAUTH_KV",
      "id": "YOUR_OAUTH_KV_ID_HERE"  // ← Replace this
    },
    {
      "binding": "MONARCH_KV",
      "id": "YOUR_MONARCH_KV_ID_HERE"  // ← Replace this
    }
  ]
}
```

---

## 🔐 Step 4: Set Secrets

Add your OAuth credentials and encryption key as Cloudflare secrets:

### Production Secrets

```bash
# GitHub OAuth (Production)
npx wrangler secret put GITHUB_CLIENT_ID
# Enter: Ov23liH3Uqf931Lo2kZ7

npx wrangler secret put GITHUB_CLIENT_SECRET
# Enter: a83e1e064997bdab0a16f091b65bfecfbe35166f

# Cookie Encryption Key
npx wrangler secret put COOKIE_ENCRYPTION_KEY
# Enter: N5guZto31O7Ly8RclsxtgeGMPLHbXOYBW7keJBK//0U=
```

**Security Note:** These secrets are encrypted at rest and never exposed in code or logs.

---

## 🧪 Step 5: Local Development Setup

For local development with `wrangler dev`, create a `.dev.vars` file:

```bash
cd worker
cp .dev.vars.example .dev.vars
```

Edit `.dev.vars` with your development credentials:

```bash
# GitHub OAuth - Development
GITHUB_CLIENT_ID=Ov23liXRuGAyLQrj7DCS
GITHUB_CLIENT_SECRET=ab2022806cdca698847dab35e6ec973cfbb94a04

# Cookie Encryption
COOKIE_ENCRYPTION_KEY=N5guZto31O7Ly8RclsxtgeGMPLHbXOYBW7keJBK//0U=
```

**⚠️ NEVER commit `.dev.vars` to git!** (Already in `.gitignore`)

---

## 🚀 Step 6: Deploy to Production

Deploy your worker to Cloudflare:

```bash
npm run deploy
```

Or with full output:

```bash
npx wrangler deploy --minify
```

**Expected Output:**
```
✨ Built successfully
🌍 Deploying...
✅ Deployed to https://monarch-mcp.tm3.workers.dev
```

---

## 🧪 Step 7: Test Locally (Optional)

Before deploying, test locally:

```bash
npm run dev
```

Visit: `http://localhost:8787`

---

## ✅ Step 8: Verify Deployment

### Test the Homepage

Visit: https://monarch-mcp.tm3.workers.dev

You should see the Monarch MCP homepage with a "Login with GitHub" button.

### Test Authentication Flow

1. Click "Login with GitHub"
2. Authorize the OAuth app
3. You should be redirected to the dashboard
4. Visit `/auth/refresh` to add your Monarch Money token

### Test Health Endpoint

```bash
curl https://monarch-mcp.tm3.workers.dev/health
```

Expected response:
```json
{"status":"ok","service":"Monarch MCP Server"}
```

---

## 🔄 Step 9: Set Up Monarch Money Token

1. Visit: https://monarch-mcp.tm3.workers.dev/auth/login
2. Authenticate with GitHub
3. Go to: https://monarch-mcp.tm3.workers.dev/auth/refresh
4. Enter your Monarch Money credentials
5. Enter 2FA code if you have MFA enabled
6. Click "Authenticate"

Your Monarch Money token is now stored securely in Cloudflare KV (encrypted at rest) and will last 90 days.

---

## 🤖 Step 10: Connect Claude Desktop

Add this configuration to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "Monarch Money": {
      "url": "https://monarch-mcp.tm3.workers.dev/mcp",
      "transport": {
        "type": "sse"
      }
    }
  }
}
```

**Restart Claude Desktop** to load the new configuration.

---

## 🛠️ Available MCP Tools

Once connected, you'll have access to these tools in Claude Desktop:

| Tool | Description |
|------|-------------|
| `setup_authentication` | Get setup instructions |
| `check_auth_status` | Check authentication status |
| `get_accounts` | Get all financial accounts |
| `get_transactions` | Get transactions with filters |
| `get_budgets` | Get budget information |
| `get_cashflow` | Get cashflow analysis |
| `get_account_holdings` | Get investment holdings |
| `create_transaction` | Create new transaction |
| `update_transaction` | Update existing transaction |
| `refresh_accounts` | Request account data refresh |

---

## 🔧 Troubleshooting

### Issue: "No Monarch Money token found"

**Solution:** Visit `/auth/refresh` and enter your Monarch Money credentials.

### Issue: "OAuth error" during login

**Solution:**
1. Check that GitHub OAuth callback URL is correct: `https://monarch-mcp.tm3.workers.dev/auth/callback`
2. Verify secrets are set correctly: `npx wrangler secret list`

### Issue: KV namespace errors

**Solution:** Ensure KV namespace IDs in `wrangler.jsonc` match the IDs from Step 2.

### Issue: "Authentication needed" in Claude Desktop

**Solution:**
1. Test authentication at https://monarch-mcp.tm3.workers.dev/auth/login
2. Ensure Monarch token is set via `/auth/refresh`
3. Check browser cookies are working

---

## 📊 Monitoring & Logs

### View Real-Time Logs

```bash
npx wrangler tail
```

### Check Worker Analytics

Visit: https://dash.cloudflare.com → Workers & Pages → monarch-mcp → Analytics

---

## 🔄 Updating the Worker

To deploy updates:

```bash
cd worker
npm run deploy
```

The deployment is instant (no downtime).

---

## 🔐 Security Best Practices

✅ **Secrets are encrypted** at rest in Cloudflare
✅ **Sessions expire** after 7 days (can be adjusted)
✅ **Monarch tokens expire** after 90 days (auto-refresh available)
✅ **OAuth state validation** prevents CSRF attacks
✅ **HTTPOnly cookies** prevent XSS attacks
✅ **HTTPS-only** communication

---

## 📝 Environment Variables Reference

| Variable | Location | Purpose |
|----------|----------|---------|
| `GITHUB_CLIENT_ID` | Cloudflare Secret | OAuth client ID |
| `GITHUB_CLIENT_SECRET` | Cloudflare Secret | OAuth client secret |
| `COOKIE_ENCRYPTION_KEY` | Cloudflare Secret | Encrypt session cookies |
| `OAUTH_KV` | KV Namespace | Store OAuth sessions |
| `MONARCH_KV` | KV Namespace | Store Monarch tokens |

---

## 🎉 Success!

You now have a fully functional remote MCP server running on Cloudflare Workers!

**What's next?**
- Test all tools in Claude Desktop
- Set up monitoring alerts (optional)
- Add rate limiting (optional)
- Customize tool permissions (optional)

---

## 💡 Tips

1. **Token Refresh Reminder**: Set a calendar reminder to refresh your Monarch token every 60 days
2. **Multiple Users**: To add more users, they just need to authenticate via GitHub OAuth
3. **Custom Domain**: Add a custom domain in Cloudflare Dashboard → Workers & Pages → Custom Domains
4. **Rate Limiting**: Add Cloudflare rate limiting rules for production use

---

## 📞 Support

For issues or questions:
- Check logs: `npx wrangler tail`
- Review Cloudflare Dashboard: https://dash.cloudflare.com
- Test endpoints manually with curl
- Check browser console for client-side errors

---

## 🔄 Quick Reference Commands

```bash
# Deploy
npm run deploy

# View logs
npx wrangler tail

# Update secrets
npx wrangler secret put GITHUB_CLIENT_ID

# List secrets
npx wrangler secret list

# Delete a secret
npx wrangler secret delete SECRET_NAME

# Develop locally
npm run dev
```

---

**🎊 Enjoy your remote Monarch Money MCP server!**
