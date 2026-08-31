"""
Configuration module for devctl and AI-Ops system.
Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
from typing import Dict, Any

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEVCTL_STATE_DIR = Path(os.environ.get("DEVCTL_STATE_DIR", BASE_DIR / ".devctl"))
INCIDENTS_DIR = DEVCTL_STATE_DIR / "incidents"
SCREENSHOTS_DIR = DEVCTL_STATE_DIR / "screenshots"
LOGS_DIR = DEVCTL_STATE_DIR / "logs"

# Ensure directories exist
for directory in [DEVCTL_STATE_DIR, INCIDENTS_DIR, SCREENSHOTS_DIR, LOGS_DIR]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


class Config:
    """Central configuration for devctl and AI-Ops."""

    # Base domain setup (e.g. dev-server.datakrib.com)
    BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "dev-server.datakrib.com").strip()

    # Subdomain namespaces
    DEV_NAMESPACE = os.environ.get("DEV_NAMESPACE", "").strip()
    STAGING_NAMESPACE = os.environ.get("STAGING_NAMESPACE", "staging").strip()
    PROD_NAMESPACE = os.environ.get("PROD_NAMESPACE", "prod").strip()

    # Docker network for internal communication
    DOCKER_NETWORK = os.environ.get("DEVCTL_DOCKER_NETWORK", "dev-net").strip()

    # Caddy Admin API
    CADDY_ADMIN_API = os.environ.get("CADDY_ADMIN_API", "http://127.0.0.1:2019").rstrip("/")
    CADDY_INTERNAL_HOST = os.environ.get("CADDY_INTERNAL_HOST", "caddy").strip()

    # AI-Ops Monitoring Settings
    MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", "15"))
    HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "5"))
    AUTO_REMEDIATION_ENABLED = os.environ.get("AUTO_REMEDIATION_ENABLED", "true").lower() == "true"
    MAX_AUTO_RESTARTS = int(os.environ.get("MAX_AUTO_RESTARTS", "3"))

    # Metrics & Trend Detection (time-series degradation monitoring)
    METRICS_ENABLED = os.environ.get("METRICS_ENABLED", "true").lower() == "true"
    METRICS_RETENTION_HOURS = int(os.environ.get("METRICS_RETENTION_HOURS", "168"))  # 7 days
    TREND_CHECK_INTERVAL_CYCLES = int(os.environ.get("TREND_CHECK_INTERVAL_CYCLES", "20"))
    TREND_WINDOW_HOURS = float(os.environ.get("TREND_WINDOW_HOURS", "2"))
    TREND_MIN_SAMPLES = int(os.environ.get("TREND_MIN_SAMPLES", "20"))
    TREND_MEM_GROWTH_FACTOR = float(os.environ.get("TREND_MEM_GROWTH_FACTOR", "1.3"))
    TREND_LATENCY_FACTOR = float(os.environ.get("TREND_LATENCY_FACTOR", "1.5"))

    # Dashboard settings
    DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8888"))
    DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")

    # Paths
    DEVCTL_STATE_DIR = DEVCTL_STATE_DIR
    STATE_FILE = DEVCTL_STATE_DIR / "state.json"
    INCIDENTS_DIR = INCIDENTS_DIR
    SCREENSHOTS_DIR = SCREENSHOTS_DIR
    LOGS_DIR = LOGS_DIR

    @classmethod
    def get_full_domain(cls, service_slug: str, env: str = "dev") -> str:
        """
        Generate full FQDN for a service and environment.
        With wildcard *.dev-server.datakrib.com:
        - service: myapp, env: dev -> myapp.dev-server.datakrib.com
        - service: myapp, env: staging -> myapp-staging.dev-server.datakrib.com (or myapp.staging.dev-server.datakrib.com)
        """
        service_slug = service_slug.lower().strip()
        env = env.lower().strip()

        if env == "dev" or not env:
            return f"{service_slug}.{cls.BASE_DOMAIN}"
        elif env in ["staging", "stage"]:
            return f"{service_slug}-staging.{cls.BASE_DOMAIN}"
        elif env in ["prod", "production"]:
            return f"{service_slug}-prod.{cls.BASE_DOMAIN}"
        else:
            return f"{service_slug}-{env}.{cls.BASE_DOMAIN}"

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        return {
            "base_domain": cls.BASE_DOMAIN,
            "docker_network": cls.DOCKER_NETWORK,
            "caddy_admin_api": cls.CADDY_ADMIN_API,
            "monitor_interval": cls.MONITOR_INTERVAL_SECONDS,
            "auto_remediation": cls.AUTO_REMEDIATION_ENABLED,
        }
