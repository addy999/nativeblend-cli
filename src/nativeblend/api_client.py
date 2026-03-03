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

    def claim_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Claim a pending task and get the code to execute.
        Returns task details including code to run in Blender and artifact path.
        """
        try:
            response = requests.post(
                f"{self.base_url}/cli/tasks/{task_id}/claim",
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None
        except requests.RequestException:
            return None

    def completed(
        self,
        task_id: str,
        status: str = "completed",
        output: str = "",
        error: Optional[str] = None,
        artifact: Optional[Any] = None,
    ) -> bool:
        """
        Mark a task as completed and submit the Blender execution result.

        Args:
            task_id: The ID of the task to mark as completed
            status: Task status - "completed" or "failed"
            output: Blender script stdout/stderr output
            error: Error message if status is "failed"
            artifact: Open file object to upload (e.g. a rendered GLB/PNG)

        Returns:
            True if submission was successful, False otherwise
        """
        try:
            form_data: Dict[str, str] = {"status": status, "output": output}
            if error:
                form_data["error"] = error

            files = None
            if artifact is not None:
                filename = getattr(artifact, "name", "artifact")
                files = {"artifact": (filename, artifact, "application/octet-stream")}

            # Omit Content-Type so requests can set the multipart boundary automatically
            headers = (
                {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            )

            response = requests.post(
                f"{self.base_url}/cli/tasks/{task_id}/complete",
                headers=headers,
                data=form_data,
                files=files,
                timeout=self.timeout,
            )

            return response.status_code == 200
        except requests.RequestException:
            return False

    def submit_generation(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        mode: str = "standard",
    ) -> Optional[Dict[str, Any]]:
        """
        Submit a generation request to the API.

        Args:
            prompt: Natural language description of the 3D model
            image_url: Optional reference image URL or file path
            mode: Generation mode - "express", "standard", or "pro"

        Returns:
            Dictionary with generation_id and status, or None if failed
        """
        try:
            payload = {
                "prompt": prompt,
                "mode": mode,
            }
            if image_url:
                payload["image_url"] = image_url

            response = requests.post(
                f"{self.base_url}/generate",
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None
        except requests.RequestException:
            return None

    def get_generation_status(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a generation task.

        Args:
            generation_id: The ID of the generation task

        Returns:
            Dictionary with status, progress, and elapsed_time, or None if failed
        """
        try:
            response = requests.get(
                f"{self.base_url}/generate/{generation_id}/status",
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None
        except requests.RequestException:
            return None

    def get_generation_result(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the final result of a completed generation task.

        Args:
            generation_id: The ID of the generation task

        Returns:
            Dictionary with status, elapsed_time, and other result data, or None if failed
        """
        try:
            response = requests.get(
                f"{self.base_url}/generate/{generation_id}/result",
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 202:
                # Still processing
                return {"status": "PROCESSING"}
            else:
                return None
        except requests.RequestException:
            return None
