"""Sentry API Client for fetching performance and issues data."""

import os
import requests
from typing import List, Dict, Any, Optional
import statistics


class SentryClient:
    """Client for interacting with Sentry API"""

    def __init__(
        self,
        token: Optional[str] = None,
        org: Optional[str] = None,
        project_id: Optional[str] = None,
        project_slug: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.token = token or os.getenv("SENTRY_TOKEN")
        self.org = org or os.getenv("SENTRY_ORG", "org-name")
        self.project_id = project_id or os.getenv("SENTRY_PROJECT_ID", "547")
        self.project_slug = project_slug or os.getenv("SENTRY_PROJECT_SLUG", "project-slug")
        self.base_url = base_url or os.getenv("SENTRY_BASE_URL", "https://sentry.your-org.com")

        if not self.token:
            raise ValueError("SENTRY_TOKEN is required")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_transactions(
        self, period: str = "24h", limit: int = 500, sort: str = "-transaction.duration"
    ) -> List[Dict[str, Any]]:
        """Get all transactions from Sentry"""
        url = f"{self.base_url}/api/0/organizations/{self.org}/events/"
        params = {
            "statsPeriod": period,
            "project": self.project_id,
            "query": "event.type:transaction",
            "sort": sort,
            "per_page": limit,
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch transactions: {e}")

    def get_event_details(self, event_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific event including spans"""
        url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/events/{event_id}/"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch event details: {e}")

    def get_issues(
        self, period: str = "24h", limit: int = 100, query: str = ""
    ) -> List[Dict[str, Any]]:
        """Get issues/errors from Sentry"""
        url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/issues/"
        params = {"statsPeriod": period, "query": query, "per_page": limit}

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch issues: {e}")

    def analyze_slow_transactions(
        self, threshold_ms: int = 2000, period: str = "24h"
    ) -> Dict[str, Any]:
        """Analyze and group slow transactions by route"""
        transactions = self.get_transactions(period=period)

        if not transactions:
            return {"error": "No transactions found"}

        # Group by route
        routes = {}
        for trans in transactions:
            route = trans.get("transaction", "unknown")
            duration = trans.get("transaction.duration", 0)

            if route not in routes:
                routes[route] = []

            routes[route].append(
                {
                    "duration": duration,
                    "timestamp": trans.get("timestamp"),
                    "id": trans.get("id"),
                }
            )

        # Calculate stats for each route
        slow_routes = []
        for route, data in routes.items():
            durations = [d["duration"] for d in data]
            avg_duration = statistics.mean(durations)

            if avg_duration > threshold_ms or max(durations) > threshold_ms * 2:
                stats = {
                    "route": route,
                    "count": len(durations),
                    "avg_ms": round(avg_duration, 2),
                    "min_ms": round(min(durations), 2),
                    "max_ms": round(max(durations), 2),
                    "median_ms": round(statistics.median(durations), 2),
                    "p95_ms": (
                        round(statistics.quantiles(durations, n=20)[18], 2)
                        if len(durations) > 1
                        else round(durations[0], 2)
                    ),
                    "slowest_event_id": max(data, key=lambda x: x["duration"])["id"],
                }
                slow_routes.append(stats)

        # Sort by average duration
        slow_routes.sort(key=lambda x: x["avg_ms"], reverse=True)

        return {
            "total_transactions": len(transactions),
            "total_routes": len(routes),
            "slow_routes_count": len(slow_routes),
            "threshold_ms": threshold_ms,
            "period": period,
            "slow_routes": slow_routes,
        }

    def get_transaction_trace(self, event_id: str) -> Dict[str, Any]:
        """Get detailed trace information for a transaction"""
        event = self.get_event_details(event_id)

        if not event:
            return {"error": "Event not found"}

        # Extract spans
        spans = event.get("spans", [])
        analyzed_spans = []

        for span in spans:
            start = span.get("start_timestamp", 0)
            end = span.get("timestamp", 0)
            duration_ms = (end - start) * 1000 if start and end else 0

            analyzed_spans.append(
                {
                    "op": span.get("op", "unknown"),
                    "description": span.get("description", "N/A"),
                    "duration_ms": round(duration_ms, 2),
                    "tags": span.get("tags", {}),
                }
            )

        # Sort by duration
        analyzed_spans.sort(key=lambda x: x["duration_ms"], reverse=True)

        return {
            "event_id": event_id,
            "transaction": event.get("transaction"),
            "total_duration_ms": event.get("contexts", {})
            .get("trace", {})
            .get("duration", 0)
            * 1000,
            "timestamp": event.get("timestamp"),
            "spans_count": len(analyzed_spans),
            "spans": analyzed_spans[:20],  # Top 20 slowest spans
        }
