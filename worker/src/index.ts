/**
 * Monarch Money MCP Server - Cloudflare Worker
 * Main entry point with OAuth, MCP endpoints, and token refresh UI
 */

import { Hono } from 'hono';
import { getCookie, setCookie, deleteCookie } from 'hono/cookie';
import { MonarchMCP } from './mcp-server.js';
import {
  GitHubOAuth,
  SessionManager,
  MonarchTokenManager,
  OAuthStateManager,
  type Env,
  type SessionData,
} from './auth.js';
import { MonarchMoney } from './monarch-client.js';

const app = new Hono<{ Bindings: Env }>();

// Middleware to check authentication
async function requireAuth(c: any): Promise<SessionData | Response> {
  const sessionId = getCookie(c, 'session_id');
  if (!sessionId) {
    return c.redirect('/auth/login');
  }

  const sessionManager = new SessionManager(c.env.OAUTH_KV);
  const session = await sessionManager.getSession(sessionId);

  if (!session || !session.authenticated) {
    return c.redirect('/auth/login');
  }

  return session;
}

// Home page
app.get('/', (c) => {
  return c.html(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Monarch Money MCP Server</title>
      <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .button { background: #0070f3; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
        .button:hover { background: #0051cc; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
      </style>
    </head>
    <body>
      <h1>🏦 Monarch Money MCP Server</h1>
      <p>Remote Model Context Protocol server for Monarch Money financial data.</p>

      <div class="card">
        <h2>🔐 Authentication Required</h2>
        <p>You must authenticate with GitHub to use this MCP server.</p>
        <a href="/auth/login" class="button">Login with GitHub</a>
      </div>

      <div class="card">
        <h2>📡 MCP Endpoint</h2>
        <p>After authentication, connect Claude Desktop to:</p>
        <code>https://monarch-mcp.tm3.workers.dev/mcp</code>
      </div>

      <div class="card">
        <h2>🔄 Token Refresh</h2>
        <p>To refresh your Monarch Money token (required for first use and when expired):</p>
        <a href="/auth/refresh" class="button">Refresh Monarch Token</a>
      </div>
    </body>
    </html>
  `);
});

// OAuth: Login
app.get('/auth/login', async (c) => {
  const baseUrl = new URL(c.req.url).origin;
  const redirectUri = `${baseUrl}/auth/callback`;

  const oauth = new GitHubOAuth(
    c.env.GITHUB_CLIENT_ID,
    c.env.GITHUB_CLIENT_SECRET,
    redirectUri
  );

  const stateManager = new OAuthStateManager(c.env.OAUTH_KV);
  const state = await stateManager.createState();

  const authUrl = oauth.getAuthorizationUrl(state);
  return c.redirect(authUrl);
});

// OAuth: Callback
app.get('/auth/callback', async (c) => {
  const code = c.req.query('code');
  const state = c.req.query('state');

  if (!code || !state) {
    return c.html('<h1>Error: Missing code or state parameter</h1>', 400);
  }

  // Validate state
  const stateManager = new OAuthStateManager(c.env.OAUTH_KV);
  const validState = await stateManager.validateState(state);

  if (!validState) {
    return c.html('<h1>Error: Invalid OAuth state</h1>', 400);
  }

  try {
    const baseUrl = new URL(c.req.url).origin;
    const redirectUri = `${baseUrl}/auth/callback`;

    const oauth = new GitHubOAuth(
      c.env.GITHUB_CLIENT_ID,
      c.env.GITHUB_CLIENT_SECRET,
      redirectUri
    );

    // Exchange code for access token
    const accessToken = await oauth.getAccessToken(code);

    // Get user info
    const user = await oauth.getUserInfo(accessToken);

    // Create session
    const sessionManager = new SessionManager(c.env.OAUTH_KV);
    const sessionId = await sessionManager.createSession(
      String(user.id),
      user.login,
      user.email || ''
    );

    // Set session cookie
    setCookie(c, 'session_id', sessionId, {
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    return c.redirect('/dashboard');
  } catch (error) {
    console.error('OAuth error:', error);
    return c.html(`<h1>OAuth Error</h1><p>${error instanceof Error ? error.message : String(error)}</p>`, 500);
  }
});

// Dashboard (protected)
app.get('/dashboard', async (c) => {
  const sessionResult = await requireAuth(c);
  if (sessionResult instanceof Response) return sessionResult;
  const session = sessionResult as SessionData;

  // Check if Monarch token exists
  const tokenManager = new MonarchTokenManager(c.env.MONARCH_KV);
  const monarchToken = await tokenManager.getToken(session.userId);

  return c.html(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Dashboard - Monarch MCP</title>
      <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .button { background: #0070f3; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; margin: 5px; }
        .button:hover { background: #0051cc; }
        .success { background: #10b981; }
        .warning { background: #f59e0b; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 14px; }
        pre { background: #f4f4f4; padding: 15px; border-radius: 5px; overflow-x: auto; }
      </style>
    </head>
    <body>
      <h1>🏦 Monarch MCP Dashboard</h1>
      <p>Welcome, <strong>${session.username}</strong>!</p>

      <div class="card">
        <h2>🔐 Authentication Status</h2>
        <p>GitHub: <strong style="color: #10b981;">✅ Authenticated</strong></p>
        <p>Monarch Money: <strong style="color: ${monarchToken ? '#10b981' : '#f59e0b'};">${monarchToken ? '✅ Token Found' : '⚠️ No Token'}</strong></p>
        ${!monarchToken ? '<p><a href="/auth/refresh" class="button warning">Refresh Monarch Token</a></p>' : ''}
      </div>

      <div class="card">
        <h2>📡 MCP Configuration</h2>
        <p>Add this to your Claude Desktop configuration (<code>claude_desktop_config.json</code>):</p>
        <pre>{
  "mcpServers": {
    "Monarch Money": {
      "url": "https://monarch-mcp.tm3.workers.dev/mcp",
      "transport": {
        "type": "sse"
      }
    }
  }
}</pre>
      </div>

      <div class="card">
        <h2>🛠️ Actions</h2>
        <a href="/auth/refresh" class="button">Refresh Monarch Token</a>
        <a href="/auth/logout" class="button" style="background: #ef4444;">Logout</a>
      </div>
    </body>
    </html>
  `);
});

// Token Refresh UI (protected)
app.get('/auth/refresh', async (c) => {
  const sessionResult = await requireAuth(c);
  if (sessionResult instanceof Response) return sessionResult;

  return c.html(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Refresh Monarch Token</title>
      <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; }
        input { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }
        button { background: #0070f3; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%; }
        button:hover { background: #0051cc; }
        .error { color: #ef4444; margin: 10px 0; }
        .success { color: #10b981; margin: 10px 0; }
      </style>
    </head>
    <body>
      <h1>🔄 Refresh Monarch Money Token</h1>

      <div class="card">
        <h2>Enter Credentials</h2>
        <form id="tokenForm">
          <input type="email" id="email" placeholder="Monarch Money Email" required />
          <input type="password" id="password" placeholder="Password" required />
          <input type="text" id="mfaCode" placeholder="2FA Code (if enabled)" />
          <button type="submit">Authenticate</button>
        </form>
        <div id="message"></div>
      </div>

      <script>
        document.getElementById('tokenForm').addEventListener('submit', async (e) => {
          e.preventDefault();
          const email = document.getElementById('email').value;
          const password = document.getElementById('password').value;
          const mfaCode = document.getElementById('mfaCode').value;
          const messageDiv = document.getElementById('message');

          messageDiv.innerHTML = '<p>Authenticating...</p>';

          try {
            const response = await fetch('/auth/refresh', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ email, password, mfa_code: mfaCode })
            });

            const result = await response.json();

            if (response.ok) {
              messageDiv.innerHTML = '<p class="success">✅ Token refreshed successfully! Redirecting...</p>';
              setTimeout(() => window.location.href = '/dashboard', 2000);
            } else {
              messageDiv.innerHTML = '<p class="error">❌ ' + result.error + '</p>';
            }
          } catch (error) {
            messageDiv.innerHTML = '<p class="error">❌ Error: ' + error.message + '</p>';
          }
        });
      </script>
    </body>
    </html>
  `);
});

// Token Refresh Handler (protected)
app.post('/auth/refresh', async (c) => {
  const sessionResult = await requireAuth(c);
  if (sessionResult instanceof Response) return sessionResult;
  const session = sessionResult as SessionData;

  try {
    const { email, password, mfa_code } = await c.req.json();

    if (!email || !password) {
      return c.json({ error: 'Email and password required' }, 400);
    }

    let client: MonarchMoney;

    // Attempt login with or without MFA
    if (mfa_code) {
      client = await MonarchMoney.mfaAuth(email, password, mfa_code);
    } else {
      client = await MonarchMoney.login(email, password);
    }

    // Get the token (note: in real implementation, you'd need to extract this from the client)
    // For now, we'll assume the MonarchMoney class exposes the token
    const token = (client as any).token;

    if (!token) {
      return c.json({ error: 'Failed to obtain token from Monarch Money' }, 500);
    }

    // Store token
    const tokenManager = new MonarchTokenManager(c.env.MONARCH_KV);
    await tokenManager.storeToken(session.userId, token);

    return c.json({ success: true, message: 'Token refreshed successfully' });
  } catch (error) {
    console.error('Token refresh error:', error);
    return c.json({
      error: error instanceof Error ? error.message : 'Authentication failed'
    }, 401);
  }
});

// Logout
app.get('/auth/logout', async (c) => {
  const sessionId = getCookie(c, 'session_id');

  if (sessionId) {
    const sessionManager = new SessionManager(c.env.OAUTH_KV);
    await sessionManager.deleteSession(sessionId);
    deleteCookie(c, 'session_id');
  }

  return c.redirect('/');
});

// MCP Endpoint (protected)
app.all('/mcp', async (c) => {
  const sessionResult = await requireAuth(c);
  if (sessionResult instanceof Response) return sessionResult;
  const session = sessionResult as SessionData;

  // Create MCP server instance
  const mcpServer = new MonarchMCP(c.env, session.userId);
  await mcpServer.init();

  // Handle MCP request
  // Note: This is a simplified version. In production, you'd use the full MCP transport layer
  return c.json({ message: 'MCP endpoint - use with MCP transport library' });
});

// Health check
app.get('/health', (c) => {
  return c.json({ status: 'ok', service: 'Monarch MCP Server' });
});

export default app;
