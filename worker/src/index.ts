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
import {
  AuthHealthManager,
  MagicLinkManager,
} from './auth-flow.js';
import {
  generateOAuthMetadata,
  MCPOAuthManager,
  type OAuth2TokenRequest,
  type OAuth2TokenResponse,
} from './oauth-mcp.js';

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

// ========================================
// MCP OAuth 2.1 Endpoints (RFC 8414)
// ========================================

// OAuth Metadata (RFC 8414) - Required for MCP clients
app.get('/.well-known/oauth-authorization-server', (c) => {
  const baseUrl = new URL(c.req.url).origin;
  const metadata = generateOAuthMetadata(baseUrl);

  return c.json(metadata, 200, {
    'Cache-Control': 'public, max-age=3600',
  });
});

// OAuth Authorization Endpoint - For MCP clients
app.get('/oauth/authorize', async (c) => {
  const clientId = c.req.query('client_id');
  const redirectUri = c.req.query('redirect_uri');
  const state = c.req.query('state');
  const codeChallenge = c.req.query('code_challenge');
  const codeChallengeMethod = c.req.query('code_challenge_method');
  const responseType = c.req.query('response_type');

  if (!clientId || !redirectUri || !state || !codeChallenge) {
    return c.json({ error: 'invalid_request', error_description: 'Missing required parameters' }, 400);
  }

  if (responseType !== 'code') {
    return c.json({ error: 'unsupported_response_type' }, 400);
  }

  if (codeChallengeMethod !== 'S256') {
    return c.json({ error: 'invalid_request', error_description: 'Only S256 code_challenge_method is supported' }, 400);
  }

  // Check if user is already authenticated
  const sessionId = getCookie(c, 'session_id');
  const sessionManager = new SessionManager(c.env.OAUTH_KV);
  const session = sessionId ? await sessionManager.getSession(sessionId) : null;

  if (!session || !session.authenticated) {
    // Store OAuth params and redirect to GitHub login
    const baseUrl = new URL(c.req.url).origin;
    await c.env.OAUTH_KV.put(
      `oauth:pending:${state}`,
      JSON.stringify({ clientId, redirectUri, codeChallenge, codeChallengeMethod }),
      { expirationTtl: 600 }
    );

    // Redirect to GitHub OAuth login
    return c.redirect(`${baseUrl}/auth/login?oauth_state=${state}`);
  }

  // User is authenticated, generate authorization code
  const mcpOAuth = new MCPOAuthManager(c.env);
  const code = crypto.randomUUID();

  await mcpOAuth.storeAuthorizationCode(
    code,
    session.userId,
    clientId,
    redirectUri,
    codeChallenge,
    codeChallengeMethod
  );

  // Redirect back to client with authorization code
  const redirectUrl = new URL(redirectUri);
  redirectUrl.searchParams.set('code', code);
  redirectUrl.searchParams.set('state', state);

  return c.redirect(redirectUrl.toString());
});

// OAuth Token Endpoint - For MCP clients
app.post('/oauth/token', async (c) => {
  try {
    const body = await c.req.json<OAuth2TokenRequest>();

    const mcpOAuth = new MCPOAuthManager(c.env);

    // Authorization Code Grant
    if (body.grant_type === 'authorization_code') {
      if (!body.code || !body.redirect_uri || !body.code_verifier) {
        return c.json({ error: 'invalid_request' }, 400);
      }

      const result = await mcpOAuth.validateAuthorizationCode(
        body.code,
        body.code_verifier,
        body.redirect_uri
      );

      if (!result) {
        return c.json({ error: 'invalid_grant' }, 400);
      }

      // Generate tokens
      const accessToken = await mcpOAuth.generateAccessToken(result.userId, result.clientId);
      const refreshToken = await mcpOAuth.generateRefreshToken(result.userId, result.clientId);

      const response: OAuth2TokenResponse = {
        access_token: accessToken,
        token_type: 'Bearer',
        expires_in: 604800, // 7 days
        refresh_token: refreshToken,
        scope: 'mcp',
      };

      return c.json(response);
    }

    // Refresh Token Grant
    if (body.grant_type === 'refresh_token') {
      if (!body.refresh_token) {
        return c.json({ error: 'invalid_request' }, 400);
      }

      const result = await mcpOAuth.validateRefreshToken(body.refresh_token);

      if (!result) {
        return c.json({ error: 'invalid_grant' }, 400);
      }

      // Generate new access token
      const accessToken = await mcpOAuth.generateAccessToken(result.userId, result.clientId);

      const response: OAuth2TokenResponse = {
        access_token: accessToken,
        token_type: 'Bearer',
        expires_in: 604800, // 7 days
        scope: 'mcp',
      };

      return c.json(response);
    }

    return c.json({ error: 'unsupported_grant_type' }, 400);
  } catch (error) {
    console.error('Token endpoint error:', error);
    return c.json({ error: 'server_error' }, 500);
  }
});

// ========================================
// Web UI OAuth Endpoints (GitHub)
// ========================================

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

    // Check if this was part of an MCP OAuth flow
    const oauthStateParam = c.req.query('oauth_state');
    if (oauthStateParam) {
      // Get pending OAuth params
      const pendingData = await c.env.OAUTH_KV.get(`oauth:pending:${oauthStateParam}`);
      if (pendingData) {
        const params = JSON.parse(pendingData);
        // Redirect back to OAuth authorize endpoint with original params
        const authorizeUrl = new URL(`${baseUrl}/oauth/authorize`);
        authorizeUrl.searchParams.set('client_id', params.clientId);
        authorizeUrl.searchParams.set('redirect_uri', params.redirectUri);
        authorizeUrl.searchParams.set('state', oauthStateParam);
        authorizeUrl.searchParams.set('code_challenge', params.codeChallenge);
        authorizeUrl.searchParams.set('code_challenge_method', params.codeChallengeMethod);
        authorizeUrl.searchParams.set('response_type', 'code');

        return c.redirect(authorizeUrl.toString());
      }
    }

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

    // Store token with metadata
    const healthManager = new AuthHealthManager(c.env);
    await healthManager.storeTokenWithMetadata(session.userId, token, 90);

    return c.json({ success: true, message: 'Token refreshed successfully' });
  } catch (error) {
    console.error('Token refresh error:', error);
    return c.json({
      error: error instanceof Error ? error.message : 'Authentication failed'
    }, 401);
  }
});

// Magic Link Handler (no auth required - validates via magic code)
app.get('/auth/magic/:code', async (c) => {
  const code = c.req.param('code');

  if (!code) {
    return c.html('<h1>Error: Invalid magic link</h1>', 400);
  }

  try {
    const magicLinkManager = new MagicLinkManager(c.env.OAUTH_KV);
    const userId = await magicLinkManager.validateMagicLink(code);

    if (!userId) {
      return c.html(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Magic Link Expired</title>
          <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; text-align: center; }
            .error { color: #ef4444; font-size: 18px; margin: 20px 0; }
          </style>
        </head>
        <body>
          <h1>🔗 Magic Link Expired</h1>
          <p class="error">This magic link has expired or has already been used.</p>
          <p>Magic links are valid for 10 minutes and can only be used once.</p>
          <p>Please return to your conversation and use the <code>setup_wizard</code> tool to generate a new link.</p>
        </body>
        </html>
      `, 410);
    }

    // Create a session for this user
    const sessionManager = new SessionManager(c.env.OAUTH_KV);
    const sessionId = await sessionManager.createSession(userId, `user-${userId}`, '');

    // Set session cookie
    setCookie(c, 'session_id', sessionId, {
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
      maxAge: 60 * 60, // 1 hour for magic link sessions
    });

    // Redirect to token refresh page
    return c.redirect('/auth/refresh');
  } catch (error) {
    console.error('Magic link error:', error);
    return c.html(`<h1>Error</h1><p>${error instanceof Error ? error.message : String(error)}</p>`, 500);
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

// MCP Endpoint (protected) - Accepts OAuth Bearer tokens
app.all('/mcp', async (c) => {
  let userId: string;

  // Check for Bearer token (OAuth 2.1 - for MCP clients like ChatGPT)
  const authHeader = c.req.header('Authorization');

  if (authHeader && authHeader.startsWith('Bearer ')) {
    const token = authHeader.substring(7);
    const mcpOAuth = new MCPOAuthManager(c.env);
    const tokenData = await mcpOAuth.validateAccessToken(token);

    if (!tokenData) {
      return c.json(
        { error: 'invalid_token', error_description: 'The access token is invalid or expired' },
        401,
        { 'WWW-Authenticate': 'Bearer realm="MCP"' }
      );
    }

    userId = tokenData.userId;
  } else {
    // Fall back to session cookie (for web UI)
    const sessionResult = await requireAuth(c);
    if (sessionResult instanceof Response) return sessionResult;
    const session = sessionResult as SessionData;
    userId = session.userId;
  }

  // Create MCP server instance
  const mcpServer = new MonarchMCP(c.env, userId);
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
