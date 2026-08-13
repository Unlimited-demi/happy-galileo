"""
Caddy Admin API integration for dynamic reverse proxy management.
Adds, updates, lists, and removes routes dynamically without restarting Caddy.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional
from .config import Config


class CaddyManager:
    """Manages dynamic routes and reverse proxies via Caddy's Admin API."""

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = (api_url or Config.CADDY_ADMIN_API).rstrip("/")

    def _api_request(
        self, method: str, path: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send an HTTP request to Caddy's Admin API."""
        url = f"{self.api_url}{path}"
        headers = {"Content-Type": "application/json"}
        req_data = json.dumps(data).encode("utf-8") if data is not None else None

        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                body = response.read().decode("utf-8")
                return {
                    "success": True,
                    "status_code": response.status,
                    "data": json.loads(body) if body else {},
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            return {
                "success": False,
                "status_code": e.code,
                "error": f"HTTP {e.code}: {err_body}",
            }
        except Exception as e:
            return {"success": False, "status_code": 0, "error": str(e)}

    def check_health(self) -> bool:
        """Check if Caddy Admin API is reachable and responding."""
        res = self._api_request("GET", "/config/")
        return res.get("success", False)

    def add_route(
        self,
        domain: str,
        upstream_host: str,
        upstream_port: int,
        route_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically create or update a reverse proxy route in Caddy.
        Example: domain='myapp.dev.example.com' -> upstream='myapp:3000'
        """
        route_id = route_id or domain.replace(".", "_")
        upstream = f"{upstream_host}:{upstream_port}"

        # JSON route definition compatible with Caddy v2 HTTP server
        route_payload = {
            "@id": route_id,
            "match": [{"host": [domain]}],
            "handle": [
                {
                    "handler": "reverse_proxy",
                    "upstreams": [{"dial": upstream}],
                    "headers": {
                        "request": {
                            "set": {
                                "X-Forwarded-Proto": ["https"],
                                "X-Forwarded-Host": [domain],
                            }
                        }
                    },
                }
            ],
            "terminal": True,
        }

        # Check if route ID already exists, if so PUT (update), else POST (append)
        check = self._api_request("GET", f"/id/{route_id}")
        if check.get("success"):
            return self._api_request("PUT", f"/id/{route_id}", route_payload)
        else:
            # Append route to default HTTP app server routes
            # Standard path: /config/apps/http/servers/srv0/routes
            res = self._api_request(
                "POST", "/config/apps/http/servers/srv0/routes", route_payload
            )
            if not res.get("success"):
                # Fallback: create by ID directly
                return self._api_request("PUT", f"/id/{route_id}", route_payload)
            return res

    def remove_route(self, domain: str, route_id: Optional[str] = None) -> Dict[str, Any]:
        """Delete a dynamic route from Caddy."""
        route_id = route_id or domain.replace(".", "_")
        res = self._api_request("DELETE", f"/id/{route_id}")
        return res

    def get_route(self, domain: str, route_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch route definition by ID."""
        route_id = route_id or domain.replace(".", "_")
        return self._api_request("GET", f"/id/{route_id}")

    def list_routes(self) -> List[Dict[str, Any]]:
        """Retrieve all currently registered routes from Caddy."""
        res = self._api_request("GET", "/config/apps/http/servers/srv0/routes")
        if res.get("success") and isinstance(res.get("data"), list):
            return res["data"]
        return []
