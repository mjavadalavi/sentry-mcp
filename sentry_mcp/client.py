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
        # Try organization-level endpoint first (better for transactions)
        url = f"{self.base_url}/api/0/organizations/{self.org}/events/{self.project_slug}:{event_id}/"

        try:
            logger.info(f"Fetching event details from: {url}")
            response = self.session.get(url, headers=self.headers, timeout=30, verify=False)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Event data keys: {list(data.keys())}")
            logger.debug(f"Event type: {data.get('type')}")
            logger.debug(f"Spans count in response: {len(data.get('spans', []))}")
            logger.debug(f"Entries count: {len(data.get('entries', []))}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch event details: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response text: {e.response.text[:500]}")
            # Fallback to project-level endpoint
            try:
                url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/events/{event_id}/"
                logger.info(f"Trying fallback URL: {url}")
                response = self.session.get(url, headers=self.headers, timeout=30, verify=False)
                response.raise_for_status()
                return response.json()
            except:
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

    def get_issue_details(self, issue_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific issue including events and stack traces"""
        # Try organization-level endpoint first
        url = f"{self.base_url}/api/0/organizations/{self.org}/issues/{issue_id}/"

        try:
            logger.info(f"Fetching issue details from: {url}")
            response = self.session.get(url, headers=self.headers, timeout=30, verify=False)
            response.raise_for_status()
            issue_data = response.json()
            logger.debug(f"Issue data keys: {list(issue_data.keys())}")
            
            # Try multiple ways to get the latest event ID
            latest_event_id = None
            
            # Method 1: Check lastEvent field (string ID)
            if isinstance(issue_data.get("lastEvent"), str):
                latest_event_id = issue_data.get("lastEvent")
                logger.info(f"Found event ID from lastEvent string: {latest_event_id}")
            
            # Method 2: Check lastEvent as dict
            elif isinstance(issue_data.get("lastEvent"), dict):
                latest_event_id = issue_data.get("lastEvent", {}).get("id") or issue_data.get("lastEvent", {}).get("eventID")
                logger.info(f"Found event ID from lastEvent dict: {latest_event_id}")
            
            # Method 3: Check latestEvent field
            if not latest_event_id and issue_data.get("latestEvent"):
                if isinstance(issue_data.get("latestEvent"), str):
                    latest_event_id = issue_data.get("latestEvent")
                else:
                    latest_event_id = issue_data.get("latestEvent", {}).get("id") or issue_data.get("latestEvent", {}).get("eventID")
                logger.info(f"Found event ID from latestEvent: {latest_event_id}")
            
            # Method 4: Fetch latest event from events endpoint
            if not latest_event_id:
                logger.info("No event ID found in issue data, fetching from events endpoint")
                events_url = f"{self.base_url}/api/0/organizations/{self.org}/issues/{issue_id}/events/"
                events_response = self.session.get(events_url, headers=self.headers, params={"per_page": 1}, timeout=30, verify=False)
                if events_response.status_code == 200:
                    events = events_response.json()
                    if events and len(events) > 0:
                        latest_event_id = events[0].get("id") or events[0].get("eventID")
                        logger.info(f"Found event ID from events endpoint: {latest_event_id}")
            
            # Fetch detailed event data if we have an event ID
            if latest_event_id:
                logger.info(f"Fetching latest event details: {latest_event_id}")
                event_url = f"{self.base_url}/api/0/organizations/{self.org}/events/{self.project_slug}:{latest_event_id}/"
                try:
                    event_response = self.session.get(event_url, headers=self.headers, timeout=30, verify=False)
                    event_response.raise_for_status()
                    event_data = event_response.json()
                    issue_data["latestEventDetails"] = event_data
                    logger.info("Successfully fetched event details")
                except requests.exceptions.RequestException as event_error:
                    logger.warning(f"Failed to fetch event details: {event_error}")
                    # Try project-level endpoint as fallback
                    try:
                        event_url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/events/{latest_event_id}/"
                        logger.info(f"Trying fallback event URL: {event_url}")
                        event_response = self.session.get(event_url, headers=self.headers, timeout=30, verify=False)
                        event_response.raise_for_status()
                        event_data = event_response.json()
                        issue_data["latestEventDetails"] = event_data
                        logger.info("Successfully fetched event details from fallback")
                    except Exception as fallback_error:
                        logger.warning(f"Fallback also failed: {fallback_error}")
            else:
                logger.warning("Could not find latest event ID for issue")
            
            return issue_data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch issue details: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response text: {e.response.text[:500]}")
            
            # Try fallback to project-level endpoint
            try:
                url = f"{self.base_url}/api/0/projects/{self.org}/{self.project_slug}/issues/{issue_id}/"
                logger.info(f"Trying fallback issue URL: {url}")
                response = self.session.get(url, headers=self.headers, timeout=30, verify=False)
                response.raise_for_status()
                return response.json()
            except Exception as fallback_error:
                logger.error(f"Fallback failed: {fallback_error}")
                raise Exception(f"Failed to fetch issue details: {e}")

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

    def get_transaction_events(
        self, transaction_name: str, period: str = "24h", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get actual event IDs for a specific transaction"""
        url = f"{self.base_url}/api/0/organizations/{self.org}/events/"
        params = {
            "statsPeriod": period,
            "project": self.project_id,
            "query": f'event.type:transaction transaction:"{transaction_name}"',
            "sort": "-transaction.duration",  # Sort by duration descending
            "per_page": limit,
            "field": [
                "id",
                "timestamp",
                "transaction",
                "transaction.duration",
                "transaction.op",
                "http.method",
            ],
        }

        try:
            logger.info(f"Fetching events for transaction: {transaction_name}")
            response = self.session.get(url, headers=self.headers, params=params, timeout=30, verify=False)
            response.raise_for_status()
            data = response.json()
            events = data.get("data", [])
            logger.info(f"Found {len(events)} events")
            return events
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch transaction events: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response text: {e.response.text}")
            return []

    def get_route_detailed_traces(
        self, route: str, period: str = "24h", threshold_ms: int = 2000, limit: int = 5
    ) -> Dict[str, Any]:
        """Get detailed traces for a specific route including all spans"""
        # First get event IDs for this route
        events = self.get_transaction_events(route, period=period, limit=limit)

        if not events:
            return {"error": f"No events found for route: {route}"}

        # Filter events by threshold
        slow_events = [
            e for e in events
            if (e.get("transaction.duration") or 0) * 1000 >= threshold_ms
        ]

        if not slow_events:
            return {
                "route": route,
                "message": f"No events slower than {threshold_ms}ms found",
                "total_events": len(events),
                "traces": []
            }

        # Get detailed trace for each event
        traces = []
        for event in slow_events[:limit]:
            event_id = event.get("id")
            if not event_id:
                continue

            try:
                trace = self.get_transaction_trace(event_id)
                traces.append(trace)
            except Exception as e:
                logger.error(f"Failed to get trace for event {event_id}: {e}")
                continue

        return {
            "route": route,
            "period": period,
            "threshold_ms": threshold_ms,
            "total_events": len(events),
            "slow_events_count": len(slow_events),
            "traces_analyzed": len(traces),
            "traces": traces
        }

    def get_transaction_trace(self, event_id: str) -> Dict[str, Any]:
        """Get detailed trace information for a transaction"""
        event = self.get_event_details(event_id)

        if not event:
            return {"error": "Event not found"}

        # Extract spans from entries (Sentry stores spans in entries, not root level)
        spans = []
        for entry in event.get("entries", []):
            if entry.get("type") == "spans":
                spans = entry.get("data", [])
                break

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
                    "data": span.get("data", {}),
                }
            )

        # Sort by duration
        analyzed_spans.sort(key=lambda x: x["duration_ms"], reverse=True)

        # Calculate total duration from startTimestamp and endTimestamp
        start_ts = event.get("startTimestamp")
        end_ts = event.get("endTimestamp")
        total_duration_ms = 0
        if start_ts and end_ts:
            total_duration_ms = (end_ts - start_ts) * 1000

        return {
            "event_id": event_id,
            "transaction": event.get("title") or event.get("transaction") or "Unknown",
            "total_duration_ms": total_duration_ms,
            "timestamp": event.get("dateReceived"),
            "spans_count": len(analyzed_spans),
            "spans": analyzed_spans[:20],  # Top 20 slowest spans
        }
