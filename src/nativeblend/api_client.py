import requests
import websocket
import certifi
import json
import time
import tenacity
from typing import Optional, Dict, Any, Callable
from urllib.parse import urljoin
from .config import config
from .agent.states import AgentState, SessionInfo, StepResponse


class AgentAPIClient:
    """Client for the v2 generation API.

    Sends local context (code, images) and receives actions to execute
    locally (render, apply_code, export, etc.).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mock: bool = False,
    ):
        self.api_key = api_key or config.get_api_key()
        self.base_url = base_url or config.get_api_endpoint()
        self.timeout = config.get_timeout()
        self._v2 = "v2/mock" if mock else "v2"

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        base = self.base_url if self.base_url.endswith("/") else self.base_url + "/"
        return urljoin(base, path.lstrip("/"))

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
        stop=tenacity.stop_after_attempt(3),
        retry=tenacity.retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def start_session(
        self,
        prompt: str,
        mode: str = "standard",
        style: str = "auto",
        image_url: Optional[str] = None,
    ) -> SessionInfo:
        """Initialize a generation session."""
        payload: Dict[str, Any] = {"prompt": prompt, "mode": mode, "style": style}
        if image_url:
            payload["image_url"] = image_url

        response = requests.post(
            self._url(f"{self._v2}/session/start"),
            headers={**self._get_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return SessionInfo(
            generation_id=data["generation_id"],
            workflow=data.get("workflow", "build"),
            current_blend_artifact_id=data.get("current_blend_artifact_id"),
            message=data.get("message", ""),
        )


    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
        stop=tenacity.stop_after_attempt(3),
        retry=tenacity.retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def start_editor_session(
        self,
        prompt: str,
        blend_file: str,
        mode: str = "standard",
        style: str = "auto",
        image_url: Optional[str] = None,
    ) -> SessionInfo:
        """Initialize an editor session by uploading a local .blend file."""
        data: Dict[str, Any] = {"prompt": prompt, "mode": mode, "style": style}
        if image_url:
            data["image_url"] = image_url

        endpoint = "v2/mock/editor/session/start" if self._v2 == "v2/mock" else "v2/editor/session/start"
        with open(blend_file, "rb") as f:
            response = requests.post(
                self._url(endpoint),
                headers=self._get_headers(),
                data=data,
                files={"blend_file": (blend_file.split("/")[-1], f, "application/octet-stream")},
                timeout=self.timeout,
            )
        response.raise_for_status()
        payload = response.json()
        return SessionInfo(
            generation_id=payload["generation_id"],
            workflow=payload.get("workflow", "edit"),
            current_blend_artifact_id=payload.get("current_blend_artifact_id"),
            message=payload.get("message", ""),
        )

    def step(
        self,
        generation_id: str,
        state: AgentState,
    ) -> StepResponse:
        """Get the next build action from the API."""
        return self._step_to_endpoint(generation_id, state, "llm/step")

    def editor_step(
        self,
        generation_id: str,
        state: AgentState,
    ) -> StepResponse:
        """Get the next editor action from the API."""
        return self._step_to_endpoint(generation_id, state, "editor/llm/step")

    def _step_to_endpoint(
        self,
        generation_id: str,
        state: AgentState,
        endpoint_suffix: str,
    ) -> StepResponse:
        context = {}
        if state.code:
            context["code"] = state.code
        if state.edit_code:
            context["edit_code"] = state.edit_code
        if state.last_output:
            context["output"] = state.last_output
        if state.last_error:
            context["error"] = state.last_error
        if state.current_blend_artifact_id:
            context["current_blend_artifact_id"] = state.current_blend_artifact_id

        headers = self._get_headers()
        files = []
        for path in state.images or []:
            files.append(("images", (path.split("/")[-1], open(path, "rb"), "image/png")))

        try:
            response = requests.post(
                self._url(f"{self._v2}/{endpoint_suffix}"),
                headers=headers,
                data={"generation_id": generation_id, "context": json.dumps(context)},
                files=files if files else None,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._parse_step_response(response.json())
        finally:
            for _, file_tuple in files:
                file_tuple[1].close()

    def end_session(
        self,
        generation_id: str,
    ) -> Dict[str, Any]:
        """Finalize and close a generation session.

        Returns:
            {"generation_id": str}
        """
        payload: Dict[str, Any] = {"generation_id": generation_id}

        response = requests.post(
            self._url(f"{self._v2}/session/end"),
            headers={**self._get_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def cancel_session(self, generation_id: str) -> bool:
        """Cancel a running session. Returns True on success."""
        try:
            response = requests.delete(
                self._url(f"{self._v2}/session/{generation_id}"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def fail_session(self, generation_id: str, error_message: str) -> bool:
        """Report a session failure to the server. Returns True on success."""
        try:
            response = requests.post(
                self._url(f"{self._v2}/session/fail"),
                headers={**self._get_headers(), "Content-Type": "application/json"},
                json={"generation_id": generation_id, "error_message": error_message},
                timeout=self.timeout,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _parse_step_response(self, data: dict) -> StepResponse:
        """Parse a raw step response dict into a StepResponse dataclass."""
        return StepResponse(
            action=data.get("action", "done"),
            message=data.get("message", ""),
            code=data.get("code"),
            render_scripts=data.get("render_scripts"),
            data={
                k: v
                for k, v in data.items()
                if k not in {"action", "message", "code", "render_scripts"}
            },
        )


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

    def list_pending_tasks(self, generation_id: str) -> Optional[list]:
        """
        List pending tasks for a specific generation.

        Args:
            generation_id: Generation ID to filter tasks by (required)

        Returns:
            List of pending tasks, or None if failed
        """
        try:
            response = requests.get(
                self._url("cli/tasks"),
                headers=self._get_headers(),
                params={"generation_id": generation_id},
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
        style: str = "auto",
    ) -> Optional[Dict[str, Any]]:
        """
        Submit a generation request to the API.

        Args:
            prompt: Natural language description of the 3D model
            image_url: Optional reference image URL or file path
            mode: Generation mode - "express", "standard", or "pro"
            style: Visual style - "auto", "low-poly", "stylized", "semi-realistic",
                   "realistic", "cartoon", "geometric", "voxel", or "retro"

        Returns:
            Dictionary with generation_id and status, or None if failed
        """
        try:
            payload = {
                "prompt": prompt,
                "mode": mode,
                "style": style,
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

    def resume_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """
        Resume an interrupted generation from its last checkpoint.

        Args:
            generation_id: The ID of the generation to resume

        Returns:
            Dictionary with generation_id and status, or error info if failed
        """
        try:
            response = requests.post(
                self._url(f"generate/{generation_id}/resume"),
                headers=self._get_headers(),
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

    def list_generations(
        self, page: int = 1, per_page: int = 20
    ) -> Optional[Dict[str, Any]]:
        """List the current user's generations with pagination."""
        try:
            response = requests.get(
                self._url("cli/generations"),
                headers=self._get_headers(),
                params={"page": page, "per_page": per_page},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException:
            return None

    def get_generation_artifacts(self, generation_id: str) -> Optional[list]:
        """Get all artifacts (images, etc.) for a generation."""
        try:
            response = requests.get(
                self._url(f"generate/{generation_id}/artifacts"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json().get("artifacts", [])
            return None
        except requests.RequestException:
            return None

    def get_generation_checkpoints(self, generation_id: str) -> Optional[list]:
        """Get checkpoint metadata for a generation (no code)."""
        try:
            response = requests.get(
                self._url(f"generate/{generation_id}/checkpoints"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json().get("checkpoints", [])
            return None
        except requests.RequestException:
            return None

    def get_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """Fetch generation metadata including prompt, mode, style, status."""
        try:
            response = requests.get(
                self._url(f"generate/{generation_id}"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException:
            return None

    def export_checkpoint(
        self, generation_id: str, checkpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """Trigger backend export of a checkpoint. Returns download URLs for files."""
        try:
            response = requests.post(
                self._url(
                    f"generate/{generation_id}/checkpoints/{checkpoint_id}/export"
                ),
                headers=self._get_headers(),
                timeout=300,  # Blender exports can be slow
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException:
            return None

    def get_generation_code(self, generation_id: str) -> Optional[str]:
        """Fetch the latest working Blender code for a generation."""
        try:
            response = requests.get(
                self._url(f"generate/{generation_id}/code"),
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json().get("code")
            return None
        except requests.RequestException:
            return None

    def export_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        """Trigger backend export and get download URLs for .glb and .blend files."""
        try:
            response = requests.post(
                self._url(f"generate/{generation_id}/export"),
                headers=self._get_headers(),
                timeout=180,  # Export can take a while
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException:
            return None

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
                return (
                    status
                    if isinstance(status, str) and status in _TERMINAL_STATUSES
                    else None
                )
            except Exception:
                return None

        final_status = None
        attempt = 0

        while True:
            ws = None
            error_msg = None
            connection_was_stable = False
            try:
                ws = websocket.create_connection(
                    ws_url,
                    header=(
                        [f"Authorization: Bearer {self.api_key}"]
                        if self.api_key
                        else None
                    ),
                    timeout=10,
                    sslopt={"ca_certs": certifi.where()},
                )

                while True:
                    try:
                        raw = ws.recv()
                        # Any successful recv means the connection is alive
                        connection_was_stable = True
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
                        # Staying connected long enough to time out is also stable
                        connection_was_stable = True
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

            # Reset counter whenever the previous connection was stable so each
            # new disconnect gets a fresh budget of _MAX_RETRIES attempts.
            if connection_was_stable:
                attempt = 0

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
            attempt += 1

        return final_status
