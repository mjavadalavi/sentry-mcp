"""Sentry API Client for fetching performance and issues data."""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Any, Optional
import urllib3
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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

        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_transactions(
        self, period: str = "24h", limit: int = 50, sort: str = "-tpm"
    ) -> List[Dict[str, Any]]:
        """Get all transactions from Sentry"""
        url = f"{self.base_url}/api/0/organizations/{self.org}/events/"
        params = {
            "statsPeriod": period,
            "project": self.project_id,
            "query": "event.type:transaction",
            "sort": ["-team_key_transaction", sort],
            "per_page": limit,
            "field": [
                "team_key_transaction",
                "transaction",
                "project",
                "transaction.op",
                "http.method",
                "tpm()",
                "p50()",
                "p95()",
                "failure_rate()",
                "apdex()",
                "count_unique(user)",
                "count_miserable(user)",
                "user_misery()",
            ],
            "referrer": "api.performance.landing-table",
        }

        try:
            logger.info(f"Fetching transactions: {url}")
            logger.debug(f"Params: {params}")
            response = self.session.get(url, headers=self.headers, params=params, timeout=30, verify=False)
            response.raise_for_status()
            data = response.json()
            transactions = data.get("data", [])
            logger.info(f"Fetched {len(transactions)} transactions")
            if transactions:
                logger.debug(f"Sample transaction: {transactions[0]}")
            return transactions
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch transactions: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response text: {e.response.text}")
            raise Exception(f"Failed to fetch transactions: {e}")

    def get_event_details(self, event_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific event including spans"""
        url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/events/{event_id}/"

        try:
            response = self.session.get(url, headers=self.headers, timeout=30, verify=False)
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
            response = self.session.get(url, headers=self.headers, params=params, timeout=30, verify=False)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch issues: {e}")

    def analyze_slow_transactions(
        self, threshold_ms: int = 2000, period: str = "24h"
    ) -> Dict[str, Any]:
        """Analyze and group slow transactions by route"""
        logger.info(f"Analyzing slow transactions with threshold={threshold_ms}ms, period={period}")
        transactions = self.get_transactions(period=period)

        if not transactions:
            logger.warning("No transactions found")
            return {"error": "No transactions found"}

        logger.info(f"Analyzing {len(transactions)} transactions")
        
        # Group by route
        routes = {}
        for trans in transactions:
            route = trans.get("transaction", "unknown")
            
            # Log first transaction to debug
            if len(routes) == 0:
                logger.debug(f"First transaction data: {trans}")
            
            # p95() is already in milliseconds from Sentry API
            p95_duration = trans.get("p95()", 0) or 0
            p50_duration = trans.get("p50()", 0) or 0
            tpm = trans.get("tpm()", 0) or 0
            failure_rate = trans.get("failure_rate()", 0) or 0
            
            if route not in routes:
                routes[route] = {
                    "transaction": route,
                    "p95_ms": p95_duration,
                    "p50_ms": p50_duration,
                    "tpm": tpm,
                    "failure_rate": failure_rate,
                    "http_method": trans.get("http.method", "N/A"),
                    "transaction_op": trans.get("transaction.op", "N/A"),
                }        # Filter slow routes based on p95 threshold
        slow_routes = []
        for route, data in routes.items():
            p95_ms = data["p95_ms"]
            
            if p95_ms > threshold_ms:
                stats = {
                    "route": route,
                    "p95_ms": round(p95_ms, 2),
                    "p50_ms": round(data["p50_ms"], 2),
                    "tpm": round(data["tpm"], 2),
                    "failure_rate": round(data["failure_rate"] * 100, 2),  # Convert to percentage
                    "http_method": data["http_method"],
                    "transaction_op": data["transaction_op"],
                }
                slow_routes.append(stats)

        # Sort by p95 duration
        slow_routes.sort(key=lambda x: x["p95_ms"], reverse=True)
        
        logger.info(f"Found {len(slow_routes)} slow routes out of {len(routes)} total routes")

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
