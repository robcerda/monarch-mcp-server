/**
 * Enhanced Authentication Flow for MCP Users
 * Handles out-of-band authentication and user notifications
 */

import type { Env } from './auth.js';

export interface AuthStatus {
  authenticated: boolean;
  hasMonarchToken: boolean;
  tokenExpiry?: string;
  needsAction: boolean;
  actionRequired?: string;
  setupUrl?: string;
  magicLink?: string;
}

export interface SetupState {
  userId: string;
  step: 'github_auth' | 'monarch_token' | 'complete';
  lastUpdated: string;
  magicCode?: string;
}

/**
 * Auth Health Manager - tracks authentication state for users
 */
export class AuthHealthManager {
  constructor(private env: Env) {}

  /**
   * Check comprehensive auth status for a user
   */
  async checkAuthHealth(userId: string): Promise<AuthStatus> {
    // Check if Monarch token exists and its expiry
    const tokenKey = `monarch:token:${userId}`;
    const tokenMetaKey = `monarch:token:meta:${userId}`;

    const token = await this.env.MONARCH_KV.get(tokenKey);
    const tokenMeta = await this.env.MONARCH_KV.get(tokenMetaKey);

    let tokenExpiry: string | undefined;
    let hasValidToken = false;

    if (token && tokenMeta) {
      const meta = JSON.parse(tokenMeta);
      const expiresAtRaw = typeof meta.expiresAt === 'string' ? meta.expiresAt : undefined;

      if (expiresAtRaw) {
        const expiryDate = new Date(expiresAtRaw);
        if (!Number.isNaN(expiryDate.getTime())) {
          tokenExpiry = expiresAtRaw;
          hasValidToken = expiryDate > new Date();
        }
      }
    }

    // Determine what action is needed
    const needsAction = !token || !hasValidToken;
    let actionRequired: string | undefined;
    let setupUrl: string | undefined;

    if (needsAction) {
      if (!token) {
        actionRequired = 'initial_setup';
        setupUrl = 'https://monarch-mcp.tm3.workers.dev/auth/refresh';
      } else if (!hasValidToken) {
        actionRequired = 'token_expired';
        setupUrl = 'https://monarch-mcp.tm3.workers.dev/auth/refresh';
      }
    }

    return {
      authenticated: true, // GitHub auth (already validated)
      hasMonarchToken: !!token && hasValidToken,
      tokenExpiry,
      needsAction,
      actionRequired,
      setupUrl,
    };
  }

  /**
   * Store token with metadata
   */
  async storeTokenWithMetadata(userId: string, token: string, expiryDays: number = 90): Promise<void> {
    const tokenKey = `monarch:token:${userId}`;
    const tokenMetaKey = `monarch:token:meta:${userId}`;

    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + expiryDays);

    // Store token
    await this.env.MONARCH_KV.put(tokenKey, token, {
      expirationTtl: expiryDays * 24 * 60 * 60
    });

    // Store metadata
    await this.env.MONARCH_KV.put(tokenMetaKey, JSON.stringify({
      createdAt: new Date().toISOString(),
      expiresAt: expiresAt.toISOString(),
      userId
    }), {
      expirationTtl: expiryDays * 24 * 60 * 60
    });
  }

  /**
   * Get days until token expires
   */
  async getDaysUntilExpiry(userId: string): Promise<number | null> {
    const tokenMetaKey = `monarch:token:meta:${userId}`;
    const tokenMeta = await this.env.MONARCH_KV.get(tokenMetaKey);

    if (!tokenMeta) return null;

    const meta = JSON.parse(tokenMeta);
    const expiresAtRaw = typeof meta.expiresAt === 'string' ? meta.expiresAt : undefined;
    if (!expiresAtRaw) return null;

    const expiryDate = new Date(expiresAtRaw);
    if (Number.isNaN(expiryDate.getTime())) return null;
    const now = new Date();
    const diffTime = expiryDate.getTime() - now.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    return diffDays;
  }
}

/**
 * Magic Link Manager - for out-of-band authentication
 */
export class MagicLinkManager {
  constructor(private env: Env) {}

  /**
   * Generate a magic link for authentication
   */
  async generateMagicLink(userId: string): Promise<string> {
    const code = this.generateRandomCode(8);
    const magicKey = `magic:${code}`;

    // Store magic link mapping (10 minute expiry)
    await this.env.OAUTH_KV.put(magicKey, JSON.stringify({
      userId,
      createdAt: new Date().toISOString()
    }), {
      expirationTtl: 600 // 10 minutes
    });

    return `https://monarch-mcp.tm3.workers.dev/auth/magic/${code}`;
  }

  /**
   * Validate and consume magic link
   */
  async validateMagicLink(code: string): Promise<string | null> {
    const magicKey = `magic:${code}`;
    const data = await this.env.OAUTH_KV.get(magicKey);

    if (!data) return null;

    const parsed = JSON.parse(data);

    // Delete after use (one-time use)
    await this.env.OAUTH_KV.delete(magicKey);

    return parsed.userId;
  }

  /**
   * Generate random code
   */
  private generateRandomCode(length: number): string {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // Removed confusing characters
    let result = '';
    const randomValues = new Uint8Array(length);
    crypto.getRandomValues(randomValues);

    for (let i = 0; i < length; i++) {
      result += chars[randomValues[i] % chars.length];
    }

    return result;
  }
}

/**
 * Setup Wizard State Manager
 */
export class SetupWizardManager {
  constructor(private env: Env) {}

  /**
   * Get current setup state
   */
  async getSetupState(userId: string): Promise<SetupState | null> {
    const setupKey = `setup:state:${userId}`;
    const data = await this.env.OAUTH_KV.get(setupKey);

    if (!data) return null;

    return JSON.parse(data);
  }

  /**
   * Update setup state
   */
  async updateSetupState(userId: string, step: SetupState['step'], magicCode?: string): Promise<void> {
    const setupKey = `setup:state:${userId}`;

    const state: SetupState = {
      userId,
      step,
      lastUpdated: new Date().toISOString(),
      magicCode
    };

    await this.env.OAUTH_KV.put(setupKey, JSON.stringify(state), {
      expirationTtl: 60 * 60 * 24 // 24 hours
    });
  }

  /**
   * Clear setup state (setup complete)
   */
  async clearSetupState(userId: string): Promise<void> {
    const setupKey = `setup:state:${userId}`;
    await this.env.OAUTH_KV.delete(setupKey);
  }
}

/**
 * Generate user-friendly error messages for MCP tools
 */
export function generateAuthErrorMessage(status: AuthStatus): string {
  if (!status.needsAction) {
    return '';
  }

  let message = '🔐 **Authentication Required**\n\n';

  if (status.actionRequired === 'initial_setup') {
    message += '📋 **First-Time Setup Needed**\n\n';
    message += 'Your Monarch Money token has not been configured yet.\n\n';
    message += '**Steps to complete setup:**\n';
    message += '1. Open your web browser\n';
    message += `2. Visit: ${status.setupUrl}\n`;
    message += '3. Enter your Monarch Money email and password\n';
    message += '4. Enter your 2FA code if you have MFA enabled\n';
    message += '5. Return here and try your command again\n\n';
    message += '💡 **Tip:** Use the `setup_wizard` tool for a guided setup experience.\n\n';
    message += '✅ Your token will be stored securely for 90 days.';
  } else if (status.actionRequired === 'token_expired') {
    message += '⏰ **Token Expired**\n\n';
    message += 'Your Monarch Money authentication token has expired.\n\n';
    message += '**Steps to refresh:**\n';
    message += '1. Open your web browser\n';
    message += `2. Visit: ${status.setupUrl}\n`;
    message += '3. Re-enter your Monarch Money credentials\n';
    message += '4. Enter your 2FA code if prompted\n';
    message += '5. Return here and try your command again\n\n';
    message += `🕒 Last token expiry: ${status.tokenExpiry || 'unknown'}\n\n`;
    message += '💡 **Tip:** Tokens last 90 days. Set a calendar reminder!';
  }

  return message;
}

/**
 * Generate setup wizard instructions
 */
export function generateSetupWizardMessage(magicLink: string, daysUntilExpiry: number | null): string {
  const message = `
🧙 **Monarch Money MCP - Setup Wizard**

Welcome! Let's get your Monarch Money integration set up.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **Setup Checklist:**

✅ **Step 1: Authenticate with GitHub**
   Status: COMPLETE ✓

🔄 **Step 2: Connect Monarch Money**
   Status: NEEDED

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔗 **Your Personal Setup Link:**

${magicLink}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 **Instructions:**

1. Click or copy the link above
2. It will open in your browser (already logged in via GitHub)
3. Enter your Monarch Money credentials:
   • Email address
   • Password
   • 2FA code (if you have MFA enabled)
4. Click "Authenticate"
5. Return to this conversation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔐 **Security Notes:**

• Your credentials are NEVER stored
• Only your authentication token is saved (encrypted)
• Token is stored in Cloudflare KV (enterprise-grade encryption)
• Token lasts 90 days before needing refresh
• Magic link expires in 10 minutes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 **After Setup:**

Once authenticated, you can use these tools:
• get_accounts - View your financial accounts
• get_transactions - Access transaction history
• get_budgets - Check budget status
• get_cashflow - Analyze income/expenses
• ...and more!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❓ **Need Help?**

If you encounter issues:
• Make sure you're using the correct Monarch Money credentials
• Check that your 2FA code is current (refreshes every 30 seconds)
• Try the link again if it expired (use setup_wizard again)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⏱️ **Link expires in:** 10 minutes
🔗 **Setup URL:** ${magicLink}

Ready? Click the link above to get started! 🚀
`.trim();

  return message;
}

/**
 * Generate status report message
 */
export function generateStatusReport(status: AuthStatus, daysUntilExpiry: number | null): string {
  let message = '📊 **Monarch Money MCP - Status Report**\n\n';

  message += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';

  // GitHub Auth Status
  message += '**GitHub Authentication:**\n';
  message += status.authenticated ? '✅ Connected\n\n' : '❌ Not Connected\n\n';

  // Monarch Token Status
  message += '**Monarch Money Token:**\n';
  if (status.hasMonarchToken) {
    message += '✅ Active\n';
    if (daysUntilExpiry !== null) {
      if (daysUntilExpiry > 30) {
        message += `🟢 Expires in: ${daysUntilExpiry} days\n`;
      } else if (daysUntilExpiry > 7) {
        message += `🟡 Expires in: ${daysUntilExpiry} days (consider refreshing soon)\n`;
      } else {
        message += `🔴 Expires in: ${daysUntilExpiry} days (refresh recommended!)\n`;
      }
    }
    message += `📅 Expiry Date: ${status.tokenExpiry || 'unknown'}\n`;
  } else {
    message += '❌ Not Configured\n';
  }

  message += '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';

  // Action Required
  if (status.needsAction) {
    message += '⚠️  **Action Required:**\n\n';
    if (status.actionRequired === 'initial_setup') {
      message += 'You need to complete initial setup.\n';
      message += `🔗 Setup URL: ${status.setupUrl}\n\n`;
      message += '💡 Use the `setup_wizard` tool for guided setup.\n';
    } else if (status.actionRequired === 'token_expired') {
      message += 'Your token has expired and needs to be refreshed.\n';
      message += `🔗 Refresh URL: ${status.setupUrl}\n\n`;
      message += '💡 This only takes a minute!\n';
    }
  } else {
    message += '✅ **All Systems Ready**\n\n';
    message += 'Your MCP server is fully configured and ready to use!\n\n';
    message += '🚀 Try these commands:\n';
    message += '• `get_accounts` - View your accounts\n';
    message += '• `get_transactions` - See recent transactions\n';
    message += '• `get_budgets` - Check budget status\n';
  }

  message += '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';

  return message;
}
