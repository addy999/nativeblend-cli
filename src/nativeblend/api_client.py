import requests
import websocket
import json
import time
from typing import Optional, Dict, Any, Callable
from urllib.parse import urljoin
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

    def _url(self, path: str) -> str:
        """Join base URL with a path, handling trailing slashes correctly."""
        base = self.base_url if self.base_url.endswith("/") else self.base_url + "/"
        return urljoin(base, path.lstrip("/"))

    def validate_api_key(self) -> bool:
        """
        Validate API key by making a test request to the health endpoint.
        Returns True if the API key is valid and working.
        """
        try:
            response = requests.get(
                self._url("health"),
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
                self._url("cli/tasks"),
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
                self._url(f"cli/tasks/{task_id}/claim"),
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
                self._url(f"cli/tasks/{task_id}/complete"),
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
                self._url("generate"),
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                try:
                    error_detail = response.json().get("detail", response.text)
                except Exception:
                    error_detail = response.text or f"HTTP {response.status_code}"
                return {"error": error_detail, "status_code": response.status_code}
        except requests.RequestException as e:
            return {"error": str(e)}

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
                self._url(f"generate/{generation_id}/status"),
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
                self._url(f"generate/{generation_id}/result"),
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

    def cancel_generation(self, generation_id: str) -> bool:
        """Cancel/revoke a generation task."""
        try:
            response = requests.delete(
                self._url(f"generate/{generation_id}"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def download_file(self, url: str) -> Optional[bytes]:
        """
        Download a file from the given URL and return its content.

        Args:
            url: The URL of the file to download

        Returns:
            The raw bytes content of the file, or None if the download failed
        """
        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.content
            else:
                return None
        except requests.RequestException:
            return None

    def stream_generation_logs(
        self,
        generation_id: str,
        on_log: Callable[[str], None],
        on_check_tasks: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """
        Stream generation logs in real-time via WebSocket.

        Retries on dropped connections (up to 5 attempts, exponential back-off)
        unless a terminal status is received or confirmed via REST.

        Returns:
            Final status ("SUCCESS", "FAILURE", "REVOKED"), or None if failed
        """
        _TERMINAL_STATUSES = {"SUCCESS", "FAILURE", "REVOKED"}
        _MAX_RETRIES = 5

        ws_base = self.base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        ws_base = ws_base if ws_base.endswith("/") else ws_base + "/"
        ws_url = urljoin(ws_base, f"generate/{generation_id}/logs/stream")

        def _is_done_via_rest() -> Optional[str]:
            try:
                result = self.get_generation_status(generation_id)
                status = result and result.get("status")
                return status if status in _TERMINAL_STATUSES else None
            except Exception:
                return None

        final_status = None

        for attempt in range(_MAX_RETRIES + 1):
            ws = None
            error_msg = None
            try:
                ws = websocket.create_connection(
                    ws_url,
                    header=(
                        [f"Authorization: Bearer {self.api_key}"]
                        if self.api_key
                        else None
                    ),
                    timeout=10,
                )

                while True:
                    try:
                        raw = ws.recv()
                        if not raw:
                            if on_check_tasks:
                                on_check_tasks()
                            continue

                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            if on_check_tasks:
                                on_check_tasks()
                            continue

                        if data.get("type") == "log":
                            on_log(data.get("log", ""))
                        elif data.get("type") == "status":
                            final_status = data.get("status")
                            break
                        elif "error" in data:
                            on_log(f"Error: {data['error']}")
                            break

                        if on_check_tasks:
                            on_check_tasks()

                    except websocket.WebSocketTimeoutException:
                        if on_check_tasks:
                            on_check_tasks()
                    except websocket.WebSocketConnectionClosedException:
                        break

            except Exception as e:
                error_msg = str(e)

            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

            # Done if we have a terminal status
            if final_status in _TERMINAL_STATUSES:
                break

            # Confirm via REST before retrying
            rest_status = _is_done_via_rest()
            if rest_status:
                final_status = rest_status
                break

            if attempt >= _MAX_RETRIES:
                if error_msg:
                    on_log(f"WebSocket error: {error_msg}")
                break

            backoff = min(2**attempt, 30)
            msg = (
                f"Connection dropped ({error_msg})" if error_msg else "Connection lost"
            )
            on_log(
                f"{msg}, reconnecting in {backoff}s (attempt {attempt + 1}/{_MAX_RETRIES})..."
            )
            time.sleep(backoff)

        return final_status
