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


@dataclass
class SessionInfo:
    """session data returned by /v2/session/start."""

    generation_id: str
    message: str = ""


@dataclass
class AgentState:
    """Local agent state: tracks what the client needs for execution."""

    # Input
    prompt: str
    mode: str = "standard"
    style: str = "auto"
    image_url: Optional[str] = None

    # Session
    session: Optional[SessionInfo] = None

    # Current execution state
    code: Optional[str] = None
    images: list[str] = field(default_factory=list)  # paths to rendered PNGs

    # Last execute result
    last_output: str = ""
    last_error: Optional[str] = None

    # Loop control
    done: bool = False

    # Output directory for renders / exports
    output_dir: str = ""
