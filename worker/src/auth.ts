/**
 * OAuth and Session Management
 */

import { Hono } from 'hono';
import { getCookie, setCookie, deleteCookie } from 'hono/cookie';

export interface Env {
  OAUTH_KV: KVNamespace;
  MONARCH_KV: KVNamespace;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  COOKIE_ENCRYPTION_KEY: string;
}

export interface GitHubUser {
  id: number;
  login: string;
  email: string;
  name: string;
}

export interface SessionData {
  userId: string;
  username: string;
  email: string;
  authenticated: boolean;
}

/**
 * GitHub OAuth flow
 */
export class GitHubOAuth {
  constructor(
    private clientId: string,
    private clientSecret: string,
    private redirectUri: string
  ) {}

  /**
   * Generate OAuth authorization URL
   */
  getAuthorizationUrl(state: string): string {
    const params = new URLSearchParams({
      client_id: this.clientId,
      redirect_uri: this.redirectUri,
      scope: 'read:user user:email',
      state,
    });

    return `https://github.com/login/oauth/authorize?${params.toString()}`;
  }

  /**
   * Exchange code for access token
   */
  async getAccessToken(code: string): Promise<string> {
    const response = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        client_id: this.clientId,
        client_secret: this.clientSecret,
        code,
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to get access token: ${response.statusText}`);
    }

    const data = await response.json() as { access_token?: string; error?: string };

    if (data.error || !data.access_token) {
      throw new Error(`OAuth error: ${data.error || 'No access token'}`);
    }

    return data.access_token;
  }

  /**
   * Get user info from GitHub
   */
  async getUserInfo(accessToken: string): Promise<GitHubUser> {
    const response = await fetch('https://api.github.com/user', {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'application/vnd.github.v3+json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to get user info: ${response.statusText}`);
    }

    return await response.json() as GitHubUser;
  }
}

/**
 * Session management with KV storage
 */
export class SessionManager {
  constructor(private kv: KVNamespace) {}

  /**
   * Create a new session
   */
  async createSession(userId: string, username: string, email: string): Promise<string> {
    const sessionId = crypto.randomUUID();
    const sessionData: SessionData = {
      userId,
      username,
      email,
      authenticated: true,
    };

    // Store session in KV with 7 day TTL
    await this.kv.put(
      `session:${sessionId}`,
      JSON.stringify(sessionData),
      { expirationTtl: 60 * 60 * 24 * 7 } // 7 days
    );

    return sessionId;
  }

  /**
   * Get session data
   */
  async getSession(sessionId: string): Promise<SessionData | null> {
    const data = await this.kv.get(`session:${sessionId}`);
    if (!data) return null;

    return JSON.parse(data) as SessionData;
  }

  /**
   * Delete session
   */
  async deleteSession(sessionId: string): Promise<void> {
    await this.kv.delete(`session:${sessionId}`);
  }

  /**
   * Validate session from cookie
   */
  async validateSessionFromCookie(cookieValue: string | undefined): Promise<SessionData | null> {
    if (!cookieValue) return null;

    try {
      return await this.getSession(cookieValue);
    } catch (error) {
      console.error('Session validation error:', error);
      return null;
    }
  }
}

/**
 * Monarch token storage
 */
export class MonarchTokenManager {
  constructor(private kv: KVNamespace) {}

  /**
   * Store Monarch Money token
   */
  async storeToken(userId: string, token: string): Promise<void> {
    await this.kv.put(
      `monarch:token:${userId}`,
      token,
      { expirationTtl: 60 * 60 * 24 * 90 } // 90 days
    );
  }

  /**
   * Get Monarch Money token
   */
  async getToken(userId: string): Promise<string | null> {
    return await this.kv.get(`monarch:token:${userId}`);
  }

  /**
   * Delete Monarch Money token
   */
  async deleteToken(userId: string): Promise<void> {
    await this.kv.delete(`monarch:token:${userId}`);
  }
}

/**
 * OAuth state management
 */
export class OAuthStateManager {
  constructor(private kv: KVNamespace) {}

  /**
   * Create OAuth state
   */
  async createState(): Promise<string> {
    const state = crypto.randomUUID();
    await this.kv.put(
      `oauth:state:${state}`,
      'valid',
      { expirationTtl: 600 } // 10 minutes
    );
    return state;
  }

  /**
   * Validate OAuth state
   */
  async validateState(state: string): Promise<boolean> {
    const value = await this.kv.get(`oauth:state:${state}`);
    if (value) {
      // Delete after validation (one-time use)
      await this.kv.delete(`oauth:state:${state}`);
      return true;
    }
    return false;
  }
}
