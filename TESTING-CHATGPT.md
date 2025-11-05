# 🧪 Testing Guide: Monarch MCP Server with ChatGPT

This guide walks you through testing your Monarch Money MCP server with ChatGPT.

---

## 📋 **Prerequisites**

### **ChatGPT Requirements:**
- ✅ **ChatGPT Plus, Pro, Team, or Enterprise account** (NOT available on free plan)
- ✅ **Developer Mode enabled** (Settings → Connectors)
- ✅ **Web or Desktop app** (as of 2025, MCP is supported)

### **Deployment Requirements:**
- ✅ **Worker deployed to Cloudflare** (or running locally with `wrangler dev`)
- ✅ **KV namespaces created**
- ✅ **Secrets configured**
- ✅ **GitHub OAuth apps set up**

---

## 🚀 **Option 1: Test with Deployed Worker** (Recommended)

### **Step 1: Deploy Your Worker**

```bash
cd worker

# Authenticate with Cloudflare
npx wrangler login

# Create KV namespaces
npx wrangler kv namespace create "OAUTH_KV"
npx wrangler kv namespace create "MONARCH_KV"

# Update wrangler.jsonc with KV IDs (see DEPLOYMENT.md)

# Set production secrets
npx wrangler secret put GITHUB_CLIENT_ID
npx wrangler secret put GITHUB_CLIENT_SECRET
npx wrangler secret put COOKIE_ENCRYPTION_KEY

# Deploy!
npm run deploy
```

Expected output:
```
✨ Compiled Worker successfully
🌍 Uploading...
✅ Deployed to https://monarch-mcp.tm3.workers.dev
```

### **Step 2: Verify Deployment**

Test the health endpoint:
```bash
curl https://monarch-mcp.tm3.workers.dev/health
```

Expected response:
```json
{"status":"ok","service":"Monarch MCP Server"}
```

### **Step 3: Connect to ChatGPT**

#### **3a. Enable Developer Mode**

1. Open **ChatGPT** (web or desktop)
2. Go to **Settings** → **Connectors**
3. Enable **Developer Mode**

#### **3b. Add Custom Connector**

1. In ChatGPT, click **Settings** → **Connectors** → **Add Custom Connector**
2. Fill in the details:

```
Name: Monarch Money MCP
Description: Financial data from Monarch Money
Server URL: https://monarch-mcp.tm3.workers.dev/mcp
Transport: SSE (Server-Sent Events)
```

3. Click **Create**
4. ChatGPT will initiate connection and may prompt for OAuth

#### **3c. Authorize GitHub OAuth**

When ChatGPT connects:
1. You'll be redirected to GitHub OAuth
2. Authorize the application
3. You'll be redirected back to ChatGPT

---

## 🧪 **Option 2: Test Locally First** (Development)

### **Step 1: Start Local Dev Server**

```bash
cd worker

# Create .dev.vars file
cp .dev.vars.example .dev.vars

# Edit .dev.vars with your dev credentials
nano .dev.vars
```

Add your development credentials:
```bash
GITHUB_CLIENT_ID=Ov23liXRuGAyLQrj7DCS
GITHUB_CLIENT_SECRET=ab2022806cdca698847dab35e6ec973cfbb94a04
COOKIE_ENCRYPTION_KEY=N5guZto31O7Ly8RclsxtgeGMPLHbXOYBW7keJBK//0U=
```

Start the dev server:
```bash
npm run dev
```

Expected output:
```
⛅️ wrangler 4.45.4
-------------------
⎔ Starting local server...
[wrangler:inf] Ready on http://localhost:8787
```

### **Step 2: Test Locally in Browser**

1. Open browser to: `http://localhost:8787`
2. Click "Login with GitHub"
3. Complete OAuth flow
4. Visit: `http://localhost:8787/auth/refresh`
5. Enter Monarch Money credentials + 2FA

### **Step 3: Expose Local Server (for ChatGPT testing)**

**Option A: Using Cloudflare Tunnel** (Recommended)

```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared  # macOS
# or download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Create tunnel
cloudflared tunnel --url http://localhost:8787
```

You'll get a public URL like:
```
https://random-words-12345.trycloudflare.com
```

Use this URL in ChatGPT's custom connector.

**Option B: Using ngrok**

```bash
# Install ngrok: https://ngrok.com/download

# Start tunnel
ngrok http 8787
```

You'll get a URL like:
```
https://abc123.ngrok.io
```

Use this URL in ChatGPT's custom connector.

---

## ✅ **Step-by-Step: Testing the Authentication Flow**

### **Test 1: First-Time Setup**

1. **In ChatGPT:** Start a new chat
2. **Enable your connector:** Click + icon → Select "Monarch Money MCP"
3. **Try a tool:** "Show me my Monarch Money accounts"

**Expected Response:**
```
🔐 Authentication Required

📋 First-Time Setup Needed

Your Monarch Money token has not been configured yet.

Steps to complete setup:
1. Open your web browser
2. Visit: https://monarch-mcp.tm3.workers.dev/auth/refresh
3. Enter your Monarch Money email and password
4. Enter your 2FA code if you have MFA enabled
5. Return here and try your command again

💡 Tip: Use the `setup_wizard` tool for a guided setup experience.
```

### **Test 2: Setup Wizard**

4. **Ask ChatGPT:** "Use the setup_wizard tool"

**Expected Response:**
```
🧙 Monarch Money MCP - Setup Wizard

Your Personal Setup Link:
https://monarch-mcp.tm3.workers.dev/auth/magic/AB3CD5FG

Click or copy this link to begin setup...
```

5. **Click the magic link** (opens in browser)
6. **Browser shows:** Token refresh form (already authenticated)
7. **Enter:**
   - Monarch Money email
   - Password
   - 2FA code

8. **Click "Authenticate"**

**Expected:** Success message shown in browser

### **Test 3: Verify Authentication**

9. **Return to ChatGPT**
10. **Ask:** "Show me my Monarch Money accounts"

**Expected:** Account data returned successfully! ✅

### **Test 4: Check Status**

11. **Ask:** "Check my Monarch MCP status"

**Expected Response:**
```
📊 Monarch Money MCP - Status Report

GitHub Authentication: ✅ Connected
Monarch Money Token: ✅ Active
🟢 Expires in: 90 days
```

### **Test 5: Try Other Tools**

12. **Try transactions:** "Show my last 10 transactions"
13. **Try budgets:** "What's my budget status?"
14. **Try cashflow:** "Show my income vs expenses this month"

---

## 🔧 **Troubleshooting**

### **Issue: "Can't connect to MCP server"**

**Solutions:**
1. Check worker is deployed: `curl https://monarch-mcp.tm3.workers.dev/health`
2. Verify secrets are set: `npx wrangler secret list`
3. Check Cloudflare Workers logs: `npx wrangler tail`

### **Issue: "GitHub OAuth fails"**

**Solutions:**
1. Verify callback URL in GitHub OAuth app matches:
   - Production: `https://monarch-mcp.tm3.workers.dev/auth/callback`
   - Local: `http://localhost:8787/auth/callback`
2. Check GitHub OAuth app is active
3. Verify CLIENT_ID and CLIENT_SECRET match

### **Issue: "Magic link expired"**

**Solution:** Magic links expire after 10 minutes. Run `setup_wizard` again to generate a new link.

### **Issue: "ChatGPT doesn't show MCP connector option"**

**Solutions:**
1. Verify you have ChatGPT Plus/Pro/Team/Enterprise (not free)
2. Enable Developer Mode: Settings → Connectors → Developer Mode
3. Try ChatGPT desktop app if web doesn't work
4. Restart ChatGPT application

### **Issue: "Tools return authentication error"**

**Solution:**
1. Check token exists: Run `check_status` tool
2. If expired: Run `setup_wizard` to refresh
3. Verify KV namespaces are configured correctly

### **Issue: "2FA code invalid"**

**Solutions:**
1. Wait for next 2FA code cycle (codes refresh every 30 seconds)
2. Ensure system time is correct
3. Check you're using the correct 2FA app

---

## 📊 **Verification Checklist**

After setup, verify all components work:

### **Infrastructure:**
- [ ] Worker deployed successfully
- [ ] Health endpoint returns 200 OK
- [ ] KV namespaces created and configured
- [ ] Secrets set correctly
- [ ] GitHub OAuth apps configured

### **Authentication:**
- [ ] GitHub OAuth login works
- [ ] Magic link generation works
- [ ] Magic link validation works
- [ ] Token storage works
- [ ] Token expiry tracking works

### **MCP Tools:**
- [ ] `setup_wizard` generates magic links
- [ ] `check_status` shows token health
- [ ] `get_accounts` returns account data
- [ ] `get_transactions` returns transactions
- [ ] `get_budgets` returns budget data
- [ ] `get_cashflow` returns cashflow analysis
- [ ] Error messages are clear and actionable

### **ChatGPT Integration:**
- [ ] Custom connector connects successfully
- [ ] Tools are available in ChatGPT
- [ ] Authentication flow works end-to-end
- [ ] Data is returned correctly
- [ ] Error handling works properly

---

## 🎯 **Expected User Experience in ChatGPT**

### **First Message:**
```
You: "Show me my Monarch Money accounts"

ChatGPT: I'll use the get_accounts tool to retrieve your account information.

[Tool Error Response with setup instructions]

ChatGPT: It looks like you need to complete authentication first.
Would you like me to run the setup wizard to help you get started?
```

### **After Setup:**
```
You: "Show me my Monarch Money accounts"

ChatGPT: Let me retrieve your account information...

[Account data displayed]

ChatGPT: Here are your Monarch Money accounts:

1. Chase Checking - $2,450.32
2. Discover Savings - $15,823.45
3. Vanguard 401k - $87,392.11
...
```

---

## 📈 **Monitoring & Logs**

### **View Real-Time Logs:**

```bash
npx wrangler tail
```

### **Check Specific Events:**

```bash
# Filter for errors
npx wrangler tail --format pretty | grep ERROR

# Filter for authentication events
npx wrangler tail --format pretty | grep "auth"

# Filter for magic link usage
npx wrangler tail --format pretty | grep "magic"
```

### **Cloudflare Dashboard:**

1. Visit: https://dash.cloudflare.com
2. Go to: Workers & Pages → monarch-mcp
3. View:
   - Real-time analytics
   - Request logs
   - Error rates
   - Performance metrics

---

## 🔄 **Quick Test Script**

Save this as `test-mcp.sh`:

```bash
#!/bin/bash

echo "🧪 Testing Monarch MCP Server..."
echo ""

# Test health endpoint
echo "1. Testing health endpoint..."
curl -s https://monarch-mcp.tm3.workers.dev/health | jq
echo ""

# Test home page
echo "2. Testing home page (should return HTML)..."
curl -s https://monarch-mcp.tm3.workers.dev/ | head -5
echo ""

# Test MCP endpoint (should require auth)
echo "3. Testing MCP endpoint..."
curl -s https://monarch-mcp.tm3.workers.dev/mcp
echo ""

echo "✅ Basic tests complete!"
echo ""
echo "Next steps:"
echo "1. Connect ChatGPT to: https://monarch-mcp.tm3.workers.dev/mcp"
echo "2. Complete authentication via setup_wizard"
echo "3. Test financial data tools"
```

Run it:
```bash
chmod +x test-mcp.sh
./test-mcp.sh
```

---

## 🎉 **Success Criteria**

Your MCP server is fully working when:

✅ Health endpoint returns OK
✅ GitHub OAuth completes successfully
✅ Magic links generate and validate
✅ Monarch Money tokens can be stored
✅ Token expiry is tracked correctly
✅ All 12 tools work in ChatGPT
✅ Error messages guide users properly
✅ Authentication flow is smooth

---

## 💡 **Pro Tips**

1. **Test locally first** with `wrangler dev` before deploying
2. **Use Cloudflare Tunnel** for easy local testing with ChatGPT
3. **Monitor logs** during first tests to catch issues
4. **Check token expiry** regularly with `check_status`
5. **Set up alerts** in Cloudflare for error spikes
6. **Document** any issues for future reference

---

## 📞 **Need Help?**

If you encounter issues:
1. Check logs: `npx wrangler tail`
2. Verify deployment: `npx wrangler deployments list`
3. Test health: `curl https://monarch-mcp.tm3.workers.dev/health`
4. Review: `USER-FLOW-GUIDE.md` for detailed troubleshooting

---

**Ready to test?** Start with Option 1 (deployed worker) or Option 2 (local dev) based on your preference!

🚀 **Quick Start:** Deploy → Connect ChatGPT → Run `setup_wizard` → Test tools → Success!
