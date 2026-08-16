"""
Authentication module for ServerGuard.
Manages API keys for dashboard access and telemetry ingestion.
"""
import json
import secrets
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from .config import Config

class AuthManager:
    """Manages API keys for dashboard and telemetry authentication."""
    
    def __init__(self, auth_file: Optional[Path] = None):
        self.auth_file = auth_file or Config.BASE_DIR / "auth.json"
    
    def _load_auth(self) -> Dict[str, Any]:
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _save_auth(self, data: Dict[str, Any]):
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.auth_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def setup_keys(self) -> Dict[str, str]:
        """Generate API keys on first install. Returns the raw keys (only shown once)."""
        data = self._load_auth()
        if data.get('initialized'):
            return {'dashboard_key': '***', 'telemetry_key': '***', 'already_initialized': True}
        
        dashboard_key = secrets.token_urlsafe(32)
        telemetry_key = secrets.token_urlsafe(32)
        
        data['dashboard_key_hash'] = hashlib.sha256(dashboard_key.encode()).hexdigest()
        data['telemetry_key_hash'] = hashlib.sha256(telemetry_key.encode()).hexdigest()
        data['initialized'] = True
        self._save_auth(data)
        
        return {'dashboard_key': dashboard_key, 'telemetry_key': telemetry_key}
    
    def validate_dashboard_key(self, key: str) -> bool:
        """Validate a dashboard API key."""
        data = self._load_auth()
        if not data.get('initialized'):
            return True  # No auth configured yet, allow access
        expected = data.get('dashboard_key_hash', '')
        provided = hashlib.sha256(key.encode()).hexdigest()
        return secrets.compare_digest(expected, provided)
    
    def validate_telemetry_key(self, key: str) -> bool:
        """Validate a telemetry ingestion API key."""
        data = self._load_auth()
        if not data.get('initialized'):
            return True  # No auth configured yet, allow access
        expected = data.get('telemetry_key_hash', '')
        provided = hashlib.sha256(key.encode()).hexdigest()
        return secrets.compare_digest(expected, provided)
