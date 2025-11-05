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

export type MonarchAuthErrorCode = 'MFA_REQUIRED' | 'INVALID_CREDENTIALS' | 'UNKNOWN';

export class MonarchAuthError extends Error {
  constructor(
    message: string,
    public code: MonarchAuthErrorCode = 'UNKNOWN',
    public status?: number,
    public details?: unknown
  ) {
    super(message);
    this.name = 'MonarchAuthError';
  }
}

const BASE_HEADERS = {
  'Content-Type': 'application/json',
  'Accept': 'application/json',
  'User-Agent': 'MonarchMCP/1.0 (+https://monarch-mcp.tm3.workers.dev)',
  'Origin': 'https://app.monarchmoney.com',
  'Referer': 'https://app.monarchmoney.com/auth/login',
  'X-Requested-With': 'XMLHttpRequest',
};

function extractErrorMessage(data: unknown, fallbackText: string | null, status: number): { message: string; code: MonarchAuthErrorCode } {
  let message = `Monarch Money authentication failed (${status})`;
  let code: MonarchAuthErrorCode = status === 401 ? 'INVALID_CREDENTIALS' : 'UNKNOWN';

  const candidates: string[] = [];
  if (typeof data === 'string') {
    candidates.push(data);
  } else if (data && typeof data === 'object') {
    const detail = (data as any).detail;
    const error = (data as any).error;
    const messageField = (data as any).message;
    const nonFieldErrors = (data as any).non_field_errors;

    if (typeof detail === 'string') candidates.push(detail);
    if (typeof error === 'string') candidates.push(error);
    if (typeof messageField === 'string') candidates.push(messageField);
    if (Array.isArray(nonFieldErrors)) {
      for (const val of nonFieldErrors) {
        if (typeof val === 'string') candidates.push(val);
      }
    }
  }

  if (fallbackText && fallbackText.trim().length > 0) {
    candidates.push(fallbackText.trim());
  }

  const first = candidates.find(Boolean);
  if (first) {
    message = first;
  }

  if (/(mfa|two[-\s]?factor|totp)/i.test(message)) {
    code = 'MFA_REQUIRED';
  } else if (status === 401 && !/(mfa|two[-\s]?factor|totp)/i.test(message)) {
    code = 'INVALID_CREDENTIALS';
  }

  return { message, code };
}

interface AuthParams {
  email: string;
  password: string;
  totp?: string;
}

async function authenticate(params: AuthParams): Promise<string> {
  const body = {
    username: params.email,
    password: params.password,
    supports_mfa: true,
    trusted_device: false,
    ...(params.totp ? { totp: params.totp } : {}),
  };

  const response = await fetch('https://api.monarchmoney.com/auth/login/', {
    method: 'POST',
    headers: BASE_HEADERS,
    body: JSON.stringify(body),
  });

  const rawText = await response.text();
  let data: any = null;
  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch {
      data = rawText;
    }
  }

  if (!response.ok) {
    const parsed = extractErrorMessage(data, typeof data === 'string' ? data : rawText, response.status);
    const inferredCode =
      response.status === 403 && !params.totp
        ? 'MFA_REQUIRED'
        : parsed.code;

    throw new MonarchAuthError(parsed.message, inferredCode, response.status, data);
  }

  if (!data || typeof data !== 'object' || typeof data.token !== 'string') {
    throw new MonarchAuthError('Received an unexpected response from Monarch Money.', 'UNKNOWN', response.status, data);
  }

  return data.token;
}

export class MonarchMoney {
  private token: string;
  private baseUrl = 'https://api.monarchmoney.com/graphql';

  constructor(token: string) {
    this.token = token;
  }

  getToken(): string {
    return this.token;
  }

  /**
   * Login to Monarch Money with email and password
   */
  static async login(email: string, password: string): Promise<MonarchMoney> {
    const token = await authenticate({ email, password });
    return new MonarchMoney(token);
  }

  /**
   * Multi-factor authentication
   */
  static async mfaAuth(email: string, password: string, mfaCode: string): Promise<MonarchMoney> {
    const token = await authenticate({
      email,
      password,
      totp: mfaCode,
    });
    return new MonarchMoney(token);
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
