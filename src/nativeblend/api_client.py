import requests
from typing import Optional, Dict, Any
from .config import config


class APIClient:
    """Client for interacting with NativeBlend API"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or config.get_api_key()
        self.base_url = base_url or config.get_api_endpoint()
        self.timeout = config.get_timeout()

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def validate_api_key(self) -> bool:
        """
        Validate API key by making a test request to the health endpoint.
        Returns True if the API key is valid and working.
        """
        try:
            response = requests.get(
                f"{self.base_url}/health",
                headers=self._get_headers(),
                timeout=10,
            )
            # Health endpoint should work with valid auth
            return response.status_code == 200
        except requests.RequestException:
            return False

    def list_pending_tasks(self) -> Optional[list]:
        """List pending tasks for the current user"""
        try:
            response = requests.get(
                f"{self.base_url}/cli/tasks",
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None
        except requests.RequestException:
            return None
