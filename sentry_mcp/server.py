"""MCP Server for Sentry Performance and Issues Analysis."""

import os
from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio

from .client import SentryClient


# Initialize server
server = Server("sentry-mcp")
sentry_client = None


def get_client() -> SentryClient:
    """Get or create Sentry client instance"""
    global sentry_client
    if sentry_client is None:
        sentry_client = SentryClient()
    return sentry_client


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Sentry analysis tools"""
    return [
        Tool(
            name="get_slow_transactions",
            description=(
                "Get slow API endpoints with detailed performance statistics. "
                "Useful for identifying bottlenecks and performance issues."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "threshold_ms": {
                        "type": "integer",
                        "description": "Minimum duration in milliseconds to consider a transaction slow (default: 2000)",
                        "default": 2000,
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period to analyze (e.g., '24h', '7d', '14d')",
                        "default": "24h",
                    },
                },
            },
        ),
        Tool(
            name="analyze_transaction_trace",
            description=(
                "Deep dive into a specific transaction to see all operations (spans) "
                "and identify which parts are taking the most time. "
                "Requires an event_id from get_slow_transactions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Sentry event ID to analyze",
                    }
                },
                "required": ["event_id"],
            },
        ),
        Tool(
            name="get_performance_overview",
            description=(
                "Get overall performance metrics for all API endpoints. "
                "Shows min/max/avg/p95 response times."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Time period (default: '24h')",
                        "default": "24h",
                    }
                },
            },
        ),
        Tool(
            name="get_recent_issues",
            description=(
                "Get recent errors and exceptions from Sentry. "
                "Useful for identifying bugs and production issues. "
                "By default, filters for unresolved issues with high or medium priority."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Time period (default: '24h')",
                        "default": "24h",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of issues to return (default: 50)",
                        "default": 50,
                    },
                    "query": {
                        "type": "string",
                        "description": "Sentry query filter (default: 'is:unresolved issue.priority:[high, medium]')",
                        "default": "is:unresolved issue.priority:[high, medium]",
                    },
                },
            },
        ),
        Tool(
            name="get_issue_details",
            description=(
                "Get detailed information about a specific issue including stack traces, "
                "breadcrumbs, tags, and the latest event data. "
                "Requires an issue_id from get_recent_issues."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "Sentry issue ID to analyze",
                    }
                },
                "required": ["issue_id"],
            },
        ),
        Tool(
            name="analyze_route_performance",
            description=(
                "Analyze performance of a specific API route/endpoint. "
                "Shows detailed statistics and identifies patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "route": {
                        "type": "string",
                        "description": "Route pattern (e.g., '/api/v1/sites/{site_id}/products')",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period (default: '24h')",
                        "default": "24h",
                    },
                },
                "required": ["route"],
            },
        ),
        Tool(
            name="get_route_detailed_traces",
            description=(
                "Get detailed traces with all spans for a specific route. "
                "This shows you EXACTLY where time is spent in slow requests, "
                "including database queries, external API calls, and other operations. "
                "Perfect for identifying performance bottlenecks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "route": {
                        "type": "string",
                        "description": "Route pattern (e.g., '/api/v1/sites/{site_id}/products')",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period (default: '24h')",
                        "default": "24h",
                    },
                    "threshold_ms": {
                        "type": "integer",
                        "description": "Minimum duration in milliseconds to analyze (default: 2000)",
                        "default": 2000,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of traces to analyze (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["route"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls"""
    try:
        client = get_client()

        if name == "get_slow_transactions":
            threshold = arguments.get("threshold_ms", 2000)
            period = arguments.get("period", "24h")

            result = client.analyze_slow_transactions(threshold_ms=threshold, period=period)

            # Format output
            output = f"""🐌 Slow Transactions Analysis ({period})

📊 Summary:
- Total Transactions: {result['total_transactions']}
- Total Routes: {result['total_routes']}
- Slow Routes (>{threshold}ms): {result['slow_routes_count']}

"""
            if result["slow_routes"]:
                output += "🔥 Top Slow Routes:\n\n"
                for i, route_data in enumerate(result["slow_routes"][:10], 1):
                    output += f"""{i}. {route_data['route']}
   📈 Stats:
      Method: {route_data['http_method']} | Operation: {route_data['transaction_op']}
      P50: {route_data['p50_ms']}ms
      P95: {route_data['p95_ms']}ms
      TPM (Throughput): {route_data['tpm']} requests/min
      Failure Rate: {route_data['failure_rate']}%

"""
            else:
                output += "✅ No slow routes found!\n"

            return [TextContent(type="text", text=output)]

        elif name == "analyze_transaction_trace":
            event_id = arguments.get("event_id")

            if not event_id:
                return [TextContent(type="text", text="❌ Error: event_id is required")]

            result = client.get_transaction_trace(event_id)

            if "error" in result:
                return [TextContent(type="text", text=f"❌ Error: {result['error']}")]

            output = f"""🔍 Transaction Trace Analysis

📋 Transaction: {result['transaction']}
⏱️  Total Duration: {result['total_duration_ms']:.0f}ms
📅 Timestamp: {result['timestamp']}
🔢 Total Spans: {result['spans_count']}

⚡ Top Slowest Operations (Spans):

"""
            for i, span in enumerate(result["spans"][:10], 1):
                output += f"""{i}. [{span['op']}] {span['description'][:80]}
   Duration: {span['duration_ms']:.2f}ms
   Tags: {span.get('tags', {})}

"""

            return [TextContent(type="text", text=output)]

        elif name == "get_performance_overview":
            period = arguments.get("period", "24h")

            result = client.analyze_slow_transactions(threshold_ms=0, period=period)

            output = f"""📊 Performance Overview ({period})

Total Transactions: {result['total_transactions']}
Total Routes: {result['total_routes']}

📈 All Routes Performance:

"""
            for i, route_data in enumerate(result["slow_routes"], 1):
                output += f"""{i}. {route_data['route']}
   Method: {route_data['http_method']} | Operation: {route_data['transaction_op']}
   P50: {route_data['p50_ms']}ms | P95: {route_data['p95_ms']}ms
   TPM: {route_data['tpm']} requests/min | Failure Rate: {route_data['failure_rate']}%

"""

            return [TextContent(type="text", text=output)]

        elif name == "get_recent_issues":
            period = arguments.get("period", "24h")
            limit = arguments.get("limit", 50)
            query = arguments.get("query", "is:unresolved issue.priority:[high, medium]")

            issues = client.get_issues(period=period, limit=limit, query=query)

            if not issues:
                return [TextContent(type="text", text="✅ No issues found!")]

            output = f"""🐛 Recent Issues ({period})

Query: {query}
Total Issues: {len(issues)}

"""
            for i, issue in enumerate(issues[:20], 1):
                priority = issue.get('priority', 'unknown')
                output += f"""{i}. {issue.get('title', 'Unknown')}
   ID: {issue.get('id', 'N/A')}
   Priority: {priority} | Level: {issue.get('level', 'unknown')}
   Count: {issue.get('count', 0)} events
   First Seen: {issue.get('firstSeen', 'N/A')}
   Last Seen: {issue.get('lastSeen', 'N/A')}
   Status: {issue.get('status', 'unknown')}

"""

            return [TextContent(type="text", text=output)]

        elif name == "get_issue_details":
            issue_id = arguments.get("issue_id")

            if not issue_id:
                return [TextContent(type="text", text="❌ Error: issue_id is required")]

            try:
                issue = client.get_issue_details(issue_id)
                
                output = f"""🐛 Issue Details

Title: {issue.get('title', 'Unknown')}
ID: {issue.get('id', 'N/A')}
Status: {issue.get('status', 'unknown')}
Level: {issue.get('level', 'unknown')}
Type: {issue.get('type', 'unknown')}

📊 Statistics:
- Total Events: {issue.get('count', 0)}
- Unique Users Affected: {issue.get('userCount', 0)}
- First Seen: {issue.get('firstSeen', 'N/A')}
- Last Seen: {issue.get('lastSeen', 'N/A')}

📍 Metadata:
- Project: {issue.get('project', {}).get('name', 'N/A')}
- Platform: {issue.get('platform', 'N/A')}
- Culprit: {issue.get('culprit', 'N/A')}

"""
                
                # Add tags if available
                if issue.get('tags'):
                    output += "🏷️  Tags:\n"
                    for tag in issue['tags'][:10]:
                        output += f"   - {tag.get('key')}: {tag.get('value')}\n"
                    output += "\n"
                
                # Add latest event details if available
                if issue.get('latestEventDetails'):
                    event = issue['latestEventDetails']
                    output += f"""📋 Latest Event:
Event ID: {event.get('eventID', 'N/A')}
Timestamp: {event.get('dateCreated', 'N/A')}

"""
                    
                    # Add stack trace from entries
                    entries = event.get('entries', [])
                    exception_found = False
                    
                    for entry in entries:
                        if entry.get('type') == 'exception':
                            exception_found = True
                            output += "🔍 Exception Details:\n\n"
                            values = entry.get('data', {}).get('values', [])
                            
                            for idx, exc in enumerate(values, 1):
                                if idx > 1:
                                    output += "\n" + "─" * 60 + "\n\n"
                                
                                output += f"Exception #{idx}:\n"
                                output += f"   Type: {exc.get('type', 'Unknown')}\n"
                                output += f"   Value: {exc.get('value', 'N/A')}\n"
                                
                                # Show mechanism if available
                                mechanism = exc.get('mechanism', {})
                                if mechanism:
                                    output += f"   Handled: {mechanism.get('handled', 'N/A')}\n"
                                
                                # Show stack trace
                                stacktrace = exc.get('stacktrace', {})
                                frames = stacktrace.get('frames', [])
                                
                                if frames:
                                    output += f"\n   📚 Stack Trace ({len(frames)} frames):\n"
                                    # Show last 5 frames (most relevant)
                                    for frame in frames[-5:]:
                                        filename = frame.get('filename', 'unknown')
                                        function = frame.get('function', 'unknown')
                                        lineno = frame.get('lineNo', 'N/A')
                                        in_app = frame.get('inApp', False)
                                        
                                        # Mark in-app frames
                                        marker = "→" if in_app else " "
                                        output += f"   {marker}  {filename}:{lineno}\n"
                                        output += f"      in {function}()\n"
                                        
                                        # Show code context if available
                                        context = frame.get('context', [])
                                        if context and in_app:
                                            output += "      Code:\n"
                                            for line_no, line_code in context[-3:]:  # Last 3 lines
                                                prefix = ">>>" if line_no == lineno else "   "
                                                output += f"      {prefix} {line_no}: {line_code}\n"
                                        output += "\n"
                                
                                output += "\n"
                    
                    if not exception_found:
                        output += "ℹ️  No exception details available in latest event\n\n"

                    # Add breadcrumbs
                    breadcrumbs_found = False
                    for entry in entries:
                        if entry.get('type') == 'breadcrumbs':
                            breadcrumbs_found = True
                            output += "🍞 Breadcrumbs:\n\n"
                            breadcrumbs_data = entry.get('data', {}).get('values', [])

                            # Show last 3 breadcrumbs (most relevant)
                            for crumb in breadcrumbs_data[-3:]:
                                timestamp = crumb.get('timestamp', '')
                                # Format timestamp if it's a full ISO format
                                if timestamp and 'T' in str(timestamp):
                                    timestamp = str(timestamp).split('T')[1][:8]  # Get time part only

                                category = crumb.get('category', 'default')
                                level = crumb.get('level', 'info')
                                message = crumb.get('message', '')

                                # Level indicator
                                level_icon = {
                                    'error': '❌',
                                    'warning': '⚠️',
                                    'info': 'ℹ️',
                                    'debug': '🔍',
                                }.get(level, '•')

                                output += f"   {level_icon} [{timestamp}] [{category}]"

                                if message:
                                    output += f" {message}"

                                output += "\n"

                                # Show data if available
                                data = crumb.get('data', {})
                                if data:
                                    for key, value in data.items():
                                        output += f"      {key}: {value}\n"

                            output += "\n"
                            break

                    if not breadcrumbs_found:
                        output += "ℹ️  No breadcrumbs available in latest event\n\n"

                output += f"\n🔗 View in Sentry: {issue.get('permalink', 'N/A')}\n"
                
                return [TextContent(type="text", text=output)]
                
            except Exception as e:
                return [TextContent(type="text", text=f"❌ Error fetching issue details: {str(e)}")]

        elif name == "analyze_route_performance":
            route = arguments.get("route")
            period = arguments.get("period", "24h")

            if not route:
                return [TextContent(type="text", text="❌ Error: route is required")]

            result = client.analyze_slow_transactions(threshold_ms=0, period=period)

            # Find specific route
            route_data = None
            for r in result["slow_routes"]:
                if r["route"] == route:
                    route_data = r
                    break

            if not route_data:
                return [
                    TextContent(
                        type="text", text=f"❌ Route '{route}' not found in period {period}"
                    )
                ]

            output = f"""📊 Route Performance Analysis

Route: {route}
Period: {period}

📈 Statistics:
- HTTP Method: {route_data['http_method']}
- Transaction Operation: {route_data['transaction_op']}
- P50 Duration: {route_data['p50_ms']}ms
- P95 Duration: {route_data['p95_ms']}ms
- Throughput (TPM): {route_data['tpm']} requests/min
- Failure Rate: {route_data['failure_rate']}%

💡 Use get_route_detailed_traces to see detailed breakdown of specific events with all spans.
"""

            return [TextContent(type="text", text=output)]

        elif name == "get_route_detailed_traces":
            route = arguments.get("route")
            period = arguments.get("period", "24h")
            threshold_ms = arguments.get("threshold_ms", 2000)
            limit = arguments.get("limit", 5)

            if not route:
                return [TextContent(type="text", text="❌ Error: route is required")]

            result = client.get_route_detailed_traces(
                route=route, period=period, threshold_ms=threshold_ms, limit=limit
            )

            if "error" in result:
                return [TextContent(type="text", text=f"❌ Error: {result['error']}")]

            output = f"""🔍 Detailed Trace Analysis for Route

📋 Route: {result['route']}
⏱️  Period: {result['period']}
🎯 Threshold: >{result['threshold_ms']}ms
📊 Total Events: {result['total_events']}
🐌 Slow Events: {result['slow_events_count']}
🔎 Traces Analyzed: {result['traces_analyzed']}

"""

            if not result['traces']:
                output += result.get('message', 'No slow traces found.')
                return [TextContent(type="text", text=output)]

            # Display each trace
            for i, trace in enumerate(result['traces'], 1):
                output += f"""
{'='*70}
🔥 Trace #{i}
{'='*70}
Event ID: {trace['event_id']}
Total Duration: {trace['total_duration_ms']:.0f}ms
Timestamp: {trace['timestamp']}
Spans Count: {trace['spans_count']}

⚡ Top Slowest Operations:

"""
                for j, span in enumerate(trace['spans'][:10], 1):
                    desc = span['description'][:100]
                    output += f"""{j}. [{span['op']}] {desc}
   Duration: {span['duration_ms']:.2f}ms
   Tags: {span.get('tags', {})}

"""

            output += f"\n{'='*70}\n"
            output += "💡 Focus on the slowest spans to optimize your code!\n"

            return [TextContent(type="text", text=output)]

        else:
            return [TextContent(type="text", text=f"❌ Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]


async def main():
    """Run the MCP server"""
    # Load environment variables
    from dotenv import load_dotenv

    load_dotenv()

    # Run server
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
