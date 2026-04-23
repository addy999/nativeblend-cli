"""Main agent loop: orchestrates local generation by following API instructions.

This runner:
1. Starts a session
2. Requests the next action from the API and executes it locally
3. Repeats until the generation is complete, then ends the session

Local actions: update_code, execute, render, done.
"""

from __future__ import annotations

from typing import Optional, Callable

from ..api_client import AgentAPIClient
from ..executor import run_blender_script_local
from ..config import config
from .states import AgentState, StepResponse, Progress
from .renderer import render_views


def run_agent(
    state: AgentState,
    api: AgentAPIClient,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[str, Optional[Progress]], None]] = None,
) -> AgentState:
    """Run the local agent loop.

    Args:
        state: Initial agent state with prompt, mode, style, output_dir.
        api: AgentAPIClient instance (real or mock).
        on_log: Callback for log messages (step names, feedback, errors).
        on_progress: Callback for progress updates (step_name, progress).

    Returns:
        Updated AgentState with final code and done=True.
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    def progress(step_name: str, prog: Optional[Progress] = None) -> None:
        if on_progress:
            on_progress(step_name, prog)

    # --- Step 1: Start session ---
    log("Starting generation session...")
    state.session = api.start_session(
        prompt=state.prompt,
        mode=state.mode,
        style=state.style,
        image_url=state.image_url,
    )
    log(f"Session started. Enhanced prompt: {state.session.enhanced_prompt}")

    # --- Step 2: Log planned phases ---
    log(f"Planned {len(state.session.phases)} phase(s)")
    for i, goal in enumerate(state.session.phases):
        log(f"  Phase {i + 1}: {goal}")

    # --- Step 3: Step loop ---
    revision = 0

    while not state.done:
        resp = api.step(state.session.session_token, state)
        progress(resp.step_name, resp.progress)

        # --- Execute local action ---
        match resp.action:
            case "update_code":
                log(f"Updating code: {resp.step_name}")
                state.code = resp.code
                state.images = []
                revision += 1

            case "execute":
                log(f"Executing script: {resp.step_name}")
                if not resp.code:
                    log("ERROR: No script to execute")
                    state.done = True
                    break
                blender_path = config.get_blender_path()
                result = run_blender_script_local(
                    resp.code, blender_path=blender_path, timeout=120,
                )
                state.last_output = result.get("output", "")
                if result.get("error"):
                    state.last_error = result["error"]
                    log(f"Execution error: {state.last_error}")
                else:
                    state.last_error = None
                    log("Script executed successfully")

            case "render":
                log(f"Rendering: {resp.step_name}")
                if not resp.render_scripts:
                    log("ERROR: No render scripts provided")
                    state.done = True
                    break
                prefix = "render"
                if resp.progress:
                    prefix = resp.progress.stage or "render"
                image_paths, error = render_views(
                    resp.render_scripts,
                    state.output_dir,
                    prefix=prefix,
                    revision=revision,
                )
                if error:
                    log(f"Render error: {error}")
                    state.images = []
                else:
                    state.images = image_paths
                    log(f"Rendered {len(image_paths)} view(s)")

            case "done":
                log("Generation complete, exporting...")
                state.done = True

            case _:
                log(f"Unknown action: {resp.action}")
                state.done = True

    # --- Step 4: End session ---
    log("Ending session...")
    try:
        api.end_session(state.session.session_token)
        log("Session ended.")
    except Exception as e:
        log(f"Warning: Failed to end session cleanly: {e}")

    return state
