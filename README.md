# Sentry MCP Server

MCP Server for comprehensive Sentry monitoring including:
- 📊 Performance Analysis
- 🐛 Issues Tracking
- 🔍 Transaction Tracing
- ⚡ Bottleneck Detection

## Features

### Performance Tools
- `get_slow_transactions` - Get slow API endpoints with detailed stats
- `analyze_transaction_trace` - Deep dive into specific transaction traces
- `get_performance_overview` - Overall performance metrics
- `compare_performance` - Compare performance across time periods

### Issues Tools
- `get_recent_issues` - Get latest errors and exceptions
- `get_issue_details` - Detailed issue analysis with stack traces
- `get_issues_by_route` - Group issues by API route

## Installation

```bash
cd ~/sentry-mcp
pip install -e .
```

## Configuration

Create `.env` file:

```env
SENTRY_TOKEN=sntryu_your_token_here
SENTRY_ORG=org-name
SENTRY_PROJECT_ID=547
SENTRY_PROJECT_SLUG=project-slug
SENTRY_BASE_URL=https://sentry.your-org.com
```

## Usage with Claude Desktop

Add to `claude.json`:

```json
{
  "mcpServers": {
    "sentry": {
      "command": "python",
      "args": ["-m", "sentry_mcp"],
      "cwd": "~/sentry-mcp",
      "env": {
        "SENTRY_TOKEN": "your_token",
        "SENTRY_ORG": "org-name",
        "SENTRY_PROJECT_ID": "547",
        "SENTRY_BASE_URL": "https://sentry.your-org.com"
      }
    }
  }
}
```

## Example Queries

- "Show me the slowest API endpoints in the last 24 hours"
- "Analyze the performance of YOUR_ROUTE"
- "What are the most common errors in production?"
- "Show me transaction traces for requests over 3 seconds"
