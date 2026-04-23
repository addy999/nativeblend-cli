from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Progress:
    """Progress info returned with each step response."""

    phase: int = 0
    total_phases: int = 0
    stage: str = ""


@dataclass
class StepResponse:
    """A single step response received from the API."""

    action: str
    step_name: str = ""
    code: Optional[str] = None
    progress: Optional[Progress] = None
    render_scripts: Optional[list[str]] = None


@dataclass
class SessionInfo:
    """Session info returned when starting a generation session."""

    session_token: str
    enhanced_prompt: str
    phases: list[str] = field(default_factory=list)


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

    # Current state
    code: Optional[str] = None
    images: list[str] = field(default_factory=list)  # paths to rendered PNGs

    # Execute action output
    last_output: str = ""
    last_error: Optional[str] = None

    # Progress
    done: bool = False

    # Output
    output_dir: str = ""
