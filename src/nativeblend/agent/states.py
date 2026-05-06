from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StepResponse:
    """A single step response received from the API."""

    action: str
    message: str = ""
    code: Optional[str] = None

    # list of scene-setup scripts for render actions.
    # Ex: {"script": str, "view": str}.
    render_scripts: Optional[list[dict]] = None

    data: dict = field(default_factory=dict)


@dataclass
class SessionInfo:
    """session data returned by /v2/session/start."""

    generation_id: str
    workflow: str = "build"
    current_blend_artifact_id: Optional[str] = None
    message: str = ""


@dataclass
class AgentState:
    """Local agent state: tracks what the client needs for execution."""

    # Input
    prompt: str
    workflow: str = "build"
    blend_file: Optional[str] = None
    original_blend_file: Optional[str] = None
    mode: str = "standard"
    style: str = "auto"
    image_path: Optional[str] = None  # Local path to reference image file

    # Session
    session: Optional[SessionInfo] = None

    # Current execution state
    code: Optional[str] = None
    edit_code: Optional[str] = None
    current_blend_artifact_id: Optional[str] = None
    images: list[str] = field(default_factory=list)  # paths to rendered PNGs

    # Last execute result
    last_output: str = ""
    last_error: Optional[str] = None

    # Loop control
    done: bool = False
    error: Optional[str] = None

    # Output directory for renders / exports
    output_dir: str = ""
