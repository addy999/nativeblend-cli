"""Main agent loop: executes server-driven actions locally.

The server is fully in control of the workflow.  Each call to /v2/llm/step
returns the next action to execute plus a human-readable message to display.
The client never makes assumptions about sequencing or phases.

Supported actions (open set - new ones from the server are logged and skipped
gracefully):
    update_code  - store new code, clear prior render state
    execute      - run the provided script in headless Blender
    render       - render views using provided render scripts
    done         - generation complete, end the session
"""

from __future__ import annotations

import os
from typing import Optional, Callable

from ..api_client import AgentAPIClient
from ..executor import run_blender_script_local, export_blender_file_local
from ..config import config
from .states import AgentState, StepResponse
from .renderer import render_views


def run_agent(
    state: AgentState,
    api: AgentAPIClient,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_message: Optional[Callable[[str], None]] = None,
) -> AgentState:
    """Run the local agent loop.

    Args:
        state: Initial agent state with prompt, mode, style, output_dir.
        api: AgentAPIClient instance (real or mock).
        on_log: Callback for internal log/debug messages.
        on_message: Callback for server-supplied display messages surfaced to
                    the user.  The server controls what (if anything) is shown.

    Returns:
        Updated AgentState with final code and done=True.
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    def show(msg: str) -> None:
        if msg and on_message:
            on_message(msg)

    # --- Start session ---
    log("Starting generation session...")
    state.session = api.start_session(
        prompt=state.prompt,
        mode=state.mode,
        style=state.style,
        image_url=state.image_url,
    )
    show(state.session.message)

    # --- Step loop ---
    revision = 0

    while not state.done:
        resp: StepResponse = api.step(state.session.generation_id, state)
        show(resp.message)
        log(f"Action: {resp.action}")

        match resp.action:
            case "update_code":
                state.code = resp.code
                state.images = []
                state.last_error = None
                revision += 1

            case "execute":
                if not resp.code:
                    log("ERROR: No script to execute")
                    state.done = True
                    break
                blender_path = config.get_blender_path()
                result = run_blender_script_local(
                    resp.code,
                    blender_path=blender_path,
                    timeout=resp.data.get("timeout", 120),
                )
                state.last_output = result.get("output", "")
                if result.get("error"):
                    state.last_error = result["error"]
                    log(f"Execution error: {state.last_error}")
                else:
                    state.last_error = None
                    log("Script executed successfully")

            case "render":
                if not resp.render_scripts:
                    log("ERROR: No render scripts provided")
                    state.done = True
                    break
                prefix = resp.data.get("prefix", "render")
                image_paths, error = render_views(
                    resp.render_scripts,
                    state.output_dir,
                    prefix=prefix,
                    revision=revision,
                )
                if error:
                    log(f"Render error: {error}")
                    state.images = []
                    state.last_error = error
                else:
                    state.images = image_paths
                    state.last_error = None
                    log(f"Rendered {len(image_paths)} view(s)")

                if state.code:
                    generation_id = os.path.basename(state.output_dir)
                    blend_filename = f"{prefix}-{revision}.blend"
                    try:
                        export_blender_file_local(state.code, generation_id, filename=blend_filename)
                        log(f"Saved .blend snapshot: {blend_filename}")
                    except Exception as e:
                        log(f"Warning: could not save .blend snapshot: {e}")

            case "done":
                state.done = True

            case _:
                log(f"Unrecognised action '{resp.action}' — skipping")

    # --- End session ---
    log("Ending session...")
    try:
        api.end_session(state.session.generation_id)
        log("Session ended.")
    except Exception as e:
        log(f"Warning: Failed to end session cleanly: {e}")

    return state
