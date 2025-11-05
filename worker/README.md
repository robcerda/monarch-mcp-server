# Monarch Money MCP Worker

Remote Model Context Protocol server running on Cloudflare Workers.

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ installed
- Cloudflare account
- Wrangler CLI: `npm install -g wrangler`

### Installation

```bash
npm install
```

### Local Development

1. Create `.dev.vars` from template:
   ```bash
   cp .dev.vars.example .dev.vars
   ```

2. Add your development credentials to `.dev.vars`

3. Start development server:
   ```bash
   npm run dev
   ```

4. Visit `http://localhost:8787`

### Deployment

See [DEPLOYMENT.md](../DEPLOYMENT.md) for complete deployment instructions.

Quick deploy:

```bash
npm run deploy
```

## 📁 Project Structure

```
worker/
├── src/
│   ├── index.ts           # Main worker entry point
│   ├── mcp-server.ts      # MCP server with all tools
│   ├── auth.ts            # OAuth & session management
│   └── monarch-client.ts  # Monarch Money API client
├── package.json
├── tsconfig.json
├── wrangler.jsonc         # Cloudflare Workers config
└── .dev.vars.example      # Template for local secrets
```

## 🔐 Security

- All secrets stored as Cloudflare Secrets (encrypted at rest)
- OAuth authentication required
- Session management with KV storage
- HTTPOnly, secure cookies
- HTTPS-only communication

## 🛠️ Available Scripts

- `npm run dev` - Start local development server
- `npm run deploy` - Deploy to production
- `npm run types` - Generate TypeScript types from Wrangler

## 📚 Documentation

- [Deployment Guide](../DEPLOYMENT.md) - Complete deployment instructions
- [Main README](../README.md) - Project overview
