/**
 * Monarch Money MCP Server
 * Implements all MCP tools using Cloudflare Agents SDK
 */

import { McpAgent } from 'agents/mcp';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { MonarchMoney } from './monarch-client.js';
import type { Env } from './auth.js';

export class MonarchMCP extends McpAgent {
  server = new McpServer({
    name: 'Monarch Money MCP',
    version: '0.1.0',
  });

  constructor(private env: Env, private userId: string) {
    super();
  }

  /**
   * Get authenticated Monarch Money client
   */
  private async getMonarchClient(): Promise<MonarchMoney> {
    // Get token from KV storage
    const token = await this.env.MONARCH_KV.get(`monarch:token:${this.userId}`);

    if (!token) {
      throw new Error('No Monarch Money token found. Please refresh your session at /auth/refresh');
    }

    return new MonarchMoney(token);
  }

  /**
   * Initialize MCP server with all tools
   */
  async init() {
    // Tool 1: Setup Authentication
    this.server.tool(
      'setup_authentication',
      {},
      async () => ({
        content: [{
          type: 'text',
          text: `🔐 Monarch Money - Setup Instructions

1️⃣ Visit the token refresh page:
   https://monarch-mcp.tm3.workers.dev/auth/refresh

2️⃣ Enter your Monarch Money credentials:
   • Email and password
   • 2FA code if you have MFA enabled

3️⃣ Token will be saved securely and last for 90 days

4️⃣ Start using Monarch tools:
   • get_accounts - View all accounts
   • get_transactions - Recent transactions
   • get_budgets - Budget information

✅ Token persists for weeks/months
✅ No frequent re-authentication needed
✅ Secure encrypted storage`
        }]
      })
    );

    // Tool 2: Check Auth Status
    this.server.tool(
      'check_auth_status',
      {},
      async () => {
        const token = await this.env.MONARCH_KV.get(`monarch:token:${this.userId}`);

        const status = token
          ? '✅ Monarch Money token found in secure storage'
          : '❌ No Monarch Money token found. Visit /auth/refresh to authenticate';

        return {
          content: [{
            type: 'text',
            text: `${status}\n\n💡 User ID: ${this.userId}\n💡 Try get_accounts to test connection`
          }]
        };
      }
    );

    // Tool 3: Get Accounts
    this.server.tool(
      'get_accounts',
      {},
      async () => {
        try {
          const client = await this.getMonarchClient();
          const accounts = await client.getAccounts();

          const accountList = accounts.accounts.map(account => ({
            id: account.id,
            name: account.displayName || account.name,
            type: account.type?.name,
            balance: account.currentBalance,
            institution: account.institution?.name,
            is_active: account.isActive ?? !account.deactivatedAt
          }));

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(accountList, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error getting accounts: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 4: Get Transactions
    this.server.tool(
      'get_transactions',
      {
        limit: z.number().optional().default(100),
        offset: z.number().optional().default(0),
        start_date: z.string().optional(),
        end_date: z.string().optional(),
        account_id: z.string().optional(),
      },
      async ({ limit, offset, start_date, end_date, account_id }) => {
        try {
          const client = await this.getMonarchClient();
          const transactions = await client.getTransactions({
            limit,
            offset,
            start_date,
            end_date,
            account_id,
          });

          const txnList = (transactions.allTransactions?.results || []).map(txn => ({
            id: txn.id,
            date: txn.date,
            amount: txn.amount,
            description: txn.description,
            category: txn.category?.name,
            account: txn.account?.displayName,
            merchant: txn.merchant?.name,
            is_pending: txn.isPending || false,
          }));

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(txnList, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error getting transactions: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 5: Get Budgets
    this.server.tool(
      'get_budgets',
      {},
      async () => {
        try {
          const client = await this.getMonarchClient();
          const budgets = await client.getBudgets();

          const budgetList = budgets.budgets.map(budget => ({
            id: budget.id,
            name: budget.name,
            amount: budget.amount,
            spent: budget.spent,
            remaining: budget.remaining,
            category: budget.category?.name,
            period: budget.period,
          }));

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(budgetList, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error getting budgets: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 6: Get Cashflow
    this.server.tool(
      'get_cashflow',
      {
        start_date: z.string().optional(),
        end_date: z.string().optional(),
      },
      async ({ start_date, end_date }) => {
        try {
          const client = await this.getMonarchClient();
          const cashflow = await client.getCashflow({ start_date, end_date });

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(cashflow, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error getting cashflow: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 7: Get Account Holdings
    this.server.tool(
      'get_account_holdings',
      {
        account_id: z.string(),
      },
      async ({ account_id }) => {
        try {
          const client = await this.getMonarchClient();
          const holdings = await client.getAccountHoldings(account_id);

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(holdings, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error getting account holdings: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 8: Create Transaction
    this.server.tool(
      'create_transaction',
      {
        account_id: z.string(),
        amount: z.number(),
        description: z.string(),
        date: z.string(),
        category_id: z.string().optional(),
        merchant_name: z.string().optional(),
      },
      async ({ account_id, amount, description, date, category_id, merchant_name }) => {
        try {
          const client = await this.getMonarchClient();
          const result = await client.createTransaction({
            account_id,
            amount,
            description,
            date,
            category_id,
            merchant_name,
          });

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(result, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error creating transaction: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 9: Update Transaction
    this.server.tool(
      'update_transaction',
      {
        transaction_id: z.string(),
        amount: z.number().optional(),
        description: z.string().optional(),
        category_id: z.string().optional(),
        date: z.string().optional(),
      },
      async ({ transaction_id, amount, description, category_id, date }) => {
        try {
          const client = await this.getMonarchClient();
          const result = await client.updateTransaction({
            transaction_id,
            amount,
            description,
            category_id,
            date,
          });

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(result, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error updating transaction: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    // Tool 10: Refresh Accounts
    this.server.tool(
      'refresh_accounts',
      {},
      async () => {
        try {
          const client = await this.getMonarchClient();
          const result = await client.requestAccountsRefresh();

          return {
            content: [{
              type: 'text',
              text: JSON.stringify(result, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: 'text',
              text: `Error refreshing accounts: ${error instanceof Error ? error.message : String(error)}`
            }],
            isError: true
          };
        }
      }
    );

    console.log('✅ Monarch MCP Server initialized with 10 tools');
  }
}
