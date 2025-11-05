/**
 * MCP OAuth 2.1 Implementation
 * Implements OAuth 2.0 Authorization Server Metadata (RFC 8414)
 * and OAuth 2.1 authorization flows for MCP clients
 */

import type { Env } from './auth.js';
import { GitHubOAuth, SessionManager } from './auth.js';

export interface OAuth2Metadata {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  scopes_supported: string[];
  response_types_supported: string[];
  grant_types_supported: string[];
  code_challenge_methods_supported: string[];
  token_endpoint_auth_methods_supported: string[];
}

export interface OAuth2TokenRequest {
  grant_type: string;
  code?: string;
  redirect_uri?: string;
  client_id?: string;
  code_verifier?: string;
  refresh_token?: string;
}

export interface OAuth2TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token?: string;
  scope?: string;
}

/**
 * Generate OAuth 2.0 Authorization Server Metadata
 * Required by RFC 8414 for MCP clients
 */
export function generateOAuthMetadata(baseUrl: string): OAuth2Metadata {
  return {
    issuer: baseUrl,
    authorization_endpoint: `${baseUrl}/oauth/authorize`,
    token_endpoint: `${baseUrl}/oauth/token`,
    scopes_supported: ['mcp'],
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    code_challenge_methods_supported: ['S256'],
    token_endpoint_auth_methods_supported: ['none'], // Public client (PKCE)
  };
}

/**
 * OAuth Authorization Manager for MCP
 */
export class MCPOAuthManager {
  constructor(private env: Env) {}

  /**
   * Store authorization code with PKCE challenge
   */
  async storeAuthorizationCode(
    code: string,
    userId: string,
    clientId: string,
    redirectUri: string,
    codeChallenge: string,
    codeChallengeMethod: string
  ): Promise<void> {
    const key = `oauth:code:${code}`;

    await this.env.OAUTH_KV.put(
      key,
      JSON.stringify({
        userId,
        clientId,
        redirectUri,
        codeChallenge,
        codeChallengeMethod,
        createdAt: Date.now(),
      }),
      { expirationTtl: 600 } // 10 minutes
    );
  }

  /**
   * Validate and consume authorization code
   */
  async validateAuthorizationCode(
    code: string,
    codeVerifier: string,
    redirectUri: string
  ): Promise<{ userId: string; clientId: string } | null> {
    const key = `oauth:code:${code}`;
    const data = await this.env.OAUTH_KV.get(key);

    if (!data) {
      return null;
    }

    const authData = JSON.parse(data);

    // Verify redirect URI matches
    if (authData.redirectUri !== redirectUri) {
      return null;
    }

    // Verify PKCE challenge
    if (authData.codeChallengeMethod === 'S256') {
      const encoder = new TextEncoder();
      const data = encoder.encode(codeVerifier);
      const hash = await crypto.subtle.digest('SHA-256', data);
      const challenge = btoa(String.fromCharCode(...new Uint8Array(hash)))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');

      if (challenge !== authData.codeChallenge) {
        return null;
      }
    }

    // Delete code after use (one-time use)
    await this.env.OAUTH_KV.delete(key);

    return {
      userId: authData.userId,
      clientId: authData.clientId,
    };
  }

  /**
   * Generate access token for MCP
   */
  async generateAccessToken(userId: string, clientId: string): Promise<string> {
    const token = crypto.randomUUID();
    const key = `oauth:access:${token}`;

    await this.env.OAUTH_KV.put(
      key,
      JSON.stringify({
        userId,
        clientId,
        scope: 'mcp',
        createdAt: Date.now(),
      }),
      { expirationTtl: 60 * 60 * 24 * 7 } // 7 days
    );

    return token;
  }

  /**
   * Validate access token
   */
  async validateAccessToken(token: string): Promise<{ userId: string } | null> {
    const key = `oauth:access:${token}`;
    const data = await this.env.OAUTH_KV.get(key);

    if (!data) {
      return null;
    }

    const tokenData = JSON.parse(data);
    return { userId: tokenData.userId };
  }

  /**
   * Generate refresh token
   */
  async generateRefreshToken(userId: string, clientId: string): Promise<string> {
    const token = crypto.randomUUID();
    const key = `oauth:refresh:${token}`;

    await this.env.OAUTH_KV.put(
      key,
      JSON.stringify({
        userId,
        clientId,
        createdAt: Date.now(),
      }),
      { expirationTtl: 60 * 60 * 24 * 90 } // 90 days
    );

    return token;
  }

  /**
   * Validate and use refresh token
   */
  async validateRefreshToken(token: string): Promise<{ userId: string; clientId: string } | null> {
    const key = `oauth:refresh:${token}`;
    const data = await this.env.OAUTH_KV.get(key);

    if (!data) {
      return null;
    }

    const tokenData = JSON.parse(data);
    return {
      userId: tokenData.userId,
      clientId: tokenData.clientId,
    };
  }
}
