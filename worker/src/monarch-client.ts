/**
 * Monarch Money API Client for TypeScript/JavaScript
 * Port of the Python monarchmoney library for Cloudflare Workers
 */

export interface MonarchAccount {
  id: string;
  displayName?: string;
  name?: string;
  type?: { name?: string };
  currentBalance?: number;
  institution?: { name?: string };
  isActive?: boolean;
  deactivatedAt?: string | null;
}

export interface MonarchTransaction {
  id: string;
  date: string;
  amount: number;
  description: string;
  category?: { name?: string };
  account?: { displayName?: string };
  merchant?: { name?: string };
  isPending?: boolean;
}

export interface MonarchBudget {
  id: string;
  name: string;
  amount?: number;
  spent?: number;
  remaining?: number;
  category?: { name?: string };
  period?: string;
}

export class MonarchMoney {
  private token: string;
  private baseUrl = 'https://api.monarchmoney.com/graphql';

  constructor(token: string) {
    this.token = token;
  }

  /**
   * Login to Monarch Money with email and password
   */
  static async login(email: string, password: string): Promise<MonarchMoney> {
    const response = await fetch('https://api.monarchmoney.com/auth/login/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error(`Login failed: ${response.statusText}`);
    }

    const data = await response.json() as { token?: string };
    if (!data.token) {
      throw new Error('No token received from login');
    }

    return new MonarchMoney(data.token);
  }

  /**
   * Multi-factor authentication
   */
  static async mfaAuth(email: string, password: string, mfaCode: string): Promise<MonarchMoney> {
    const response = await fetch('https://api.monarchmoney.com/auth/login/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        password,
        totp_code: mfaCode,
      }),
    });

    if (!response.ok) {
      throw new Error(`MFA authentication failed: ${response.statusText}`);
    }

    const data = await response.json() as { token?: string };
    if (!data.token) {
      throw new Error('No token received from MFA authentication');
    }

    return new MonarchMoney(data.token);
  }

  /**
   * Execute a GraphQL query
   */
  private async query(query: string, variables?: Record<string, unknown>): Promise<any> {
    const response = await fetch(this.baseUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Token ${this.token}`,
      },
      body: JSON.stringify({ query, variables }),
    });

    if (!response.ok) {
      throw new Error(`GraphQL request failed: ${response.statusText}`);
    }

    const result = await response.json() as { data?: any; errors?: any[] };

    if (result.errors) {
      throw new Error(`GraphQL errors: ${JSON.stringify(result.errors)}`);
    }

    return result.data;
  }

  /**
   * Get all accounts
   */
  async getAccounts(): Promise<{ accounts: MonarchAccount[] }> {
    const query = `
      query GetAccounts {
        accounts {
          id
          displayName
          name
          currentBalance
          isActive
          deactivatedAt
          type {
            name
          }
          institution {
            name
          }
        }
      }
    `;

    const data = await this.query(query);
    return { accounts: data.accounts || [] };
  }

  /**
   * Get transactions with filters
   */
  async getTransactions(params: {
    limit?: number;
    offset?: number;
    start_date?: string;
    end_date?: string;
    account_id?: string;
  } = {}): Promise<{ allTransactions: { results: MonarchTransaction[] } }> {
    const { limit = 100, offset = 0, start_date, end_date, account_id } = params;

    const query = `
      query GetTransactions($limit: Int, $offset: Int, $filters: TransactionFilterInput) {
        allTransactions(limit: $limit, offset: $offset, filters: $filters) {
          results {
            id
            date
            amount
            description
            isPending
            category {
              name
            }
            account {
              displayName
            }
            merchant {
              name
            }
          }
        }
      }
    `;

    const filters: Record<string, unknown> = {};
    if (start_date) filters.startDate = start_date;
    if (end_date) filters.endDate = end_date;
    if (account_id) filters.accountId = account_id;

    const variables = {
      limit,
      offset,
      filters: Object.keys(filters).length > 0 ? filters : undefined,
    };

    const data = await this.query(query, variables);
    return data;
  }

  /**
   * Get budgets
   */
  async getBudgets(): Promise<{ budgets: MonarchBudget[] }> {
    const query = `
      query GetBudgets {
        budgets {
          id
          name
          amount
          spent
          remaining
          period
          category {
            name
          }
        }
      }
    `;

    const data = await this.query(query);
    return { budgets: data.budgets || [] };
  }

  /**
   * Get cashflow analysis
   */
  async getCashflow(params: {
    start_date?: string;
    end_date?: string;
  } = {}): Promise<any> {
    const { start_date, end_date } = params;

    const query = `
      query GetCashflow($startDate: Date, $endDate: Date) {
        cashflow(startDate: $startDate, endDate: $endDate) {
          income
          expense
          net
          categories {
            name
            amount
          }
        }
      }
    `;

    const variables: Record<string, unknown> = {};
    if (start_date) variables.startDate = start_date;
    if (end_date) variables.endDate = end_date;

    return await this.query(query, variables);
  }

  /**
   * Get account holdings (investments)
   */
  async getAccountHoldings(accountId: string): Promise<any> {
    const query = `
      query GetAccountHoldings($accountId: UUID!) {
        accountHoldings(accountId: $accountId) {
          id
          symbol
          quantity
          costBasis
          currentValue
          security {
            name
            ticker
          }
        }
      }
    `;

    return await this.query(query, { accountId });
  }

  /**
   * Create a new transaction
   */
  async createTransaction(params: {
    account_id: string;
    amount: number;
    description: string;
    date: string;
    category_id?: string;
    merchant_name?: string;
  }): Promise<any> {
    const mutation = `
      mutation CreateTransaction($input: CreateTransactionInput!) {
        createTransaction(input: $input) {
          id
          date
          amount
          description
        }
      }
    `;

    const input: Record<string, unknown> = {
      accountId: params.account_id,
      amount: params.amount,
      description: params.description,
      date: params.date,
    };

    if (params.category_id) input.categoryId = params.category_id;
    if (params.merchant_name) input.merchantName = params.merchant_name;

    return await this.query(mutation, { input });
  }

  /**
   * Update an existing transaction
   */
  async updateTransaction(params: {
    transaction_id: string;
    amount?: number;
    description?: string;
    category_id?: string;
    date?: string;
  }): Promise<any> {
    const mutation = `
      mutation UpdateTransaction($id: UUID!, $input: UpdateTransactionInput!) {
        updateTransaction(id: $id, input: $input) {
          id
          date
          amount
          description
        }
      }
    `;

    const input: Record<string, unknown> = {};
    if (params.amount !== undefined) input.amount = params.amount;
    if (params.description !== undefined) input.description = params.description;
    if (params.category_id !== undefined) input.categoryId = params.category_id;
    if (params.date !== undefined) input.date = params.date;

    return await this.query(mutation, {
      id: params.transaction_id,
      input,
    });
  }

  /**
   * Request accounts refresh
   */
  async requestAccountsRefresh(): Promise<any> {
    const mutation = `
      mutation RequestAccountsRefresh {
        requestAccountsRefresh {
          success
          message
        }
      }
    `;

    return await this.query(mutation);
  }
}
