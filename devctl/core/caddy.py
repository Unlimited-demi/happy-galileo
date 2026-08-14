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

    def get_http_server_name(self) -> str:
        """Discover the active HTTP server name in Caddy config (e.g. srv0)."""
        res = self._api_request("GET", "/config/apps/http/servers")
        if res.get("success") and isinstance(res.get("data"), dict):
            keys = list(res["data"].keys())
            if keys:
                return keys[0]
        return "srv0"

    def add_route(
        self,
        domain: str,
        upstream_host: str,
        upstream_port: int,
        route_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically create or update a reverse proxy route in Caddy with highest priority.
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

        # Check if route ID already exists, if so PUT (update)
        check = self._api_request("GET", f"/id/{route_id}")
        if check.get("success"):
            return self._api_request("PUT", f"/id/{route_id}", route_payload)

        # Prepend route to index 0 of routes array for instant match priority
        server_name = self.get_http_server_name()
        res = self._api_request(
            "PUT", f"/config/apps/http/servers/{server_name}/routes/0", route_payload
        )
        if not res.get("success"):
            # Fallback: append or direct by ID
            res = self._api_request(
                "POST", f"/config/apps/http/servers/{server_name}/routes", route_payload
            )
            if not res.get("success"):
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
        server_name = self.get_http_server_name()
        res = self._api_request("GET", f"/config/apps/http/servers/{server_name}/routes")
        if res.get("success") and isinstance(res.get("data"), list):
            return res["data"]
        return []
