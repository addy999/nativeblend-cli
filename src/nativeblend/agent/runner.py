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

In editor workflow (state.workflow == "edit"), ``execute`` and ``render`` run against state.blend_file.
"""

from __future__ import annotations

import os
from typing import Optional, Callable

from ..api_client import AgentAPIClient
from ..executor import (
    run_blender_script_local,
    export_blender_file_local,
)
from ..config import config
from .states import AgentState, StepResponse
from .renderer import render_views


def run_agent(
    state: AgentState,
    api: AgentAPIClient,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_message: Optional[Callable[[str], None]] = None,
    resume: bool = False,
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

    # --- Start session (or resume existing) ---
    if not resume:
        log(
            "Starting editor session..."
            if state.workflow == "edit"
            else "Starting generation session..."
        )
        if state.workflow == "edit":
            if not state.blend_file:
                raise ValueError("Editor workflow requires a .blend file")
            state.session = api.start_editor_session(
                prompt=state.prompt,
                blend_file=state.blend_file,
                mode=state.mode,
                style=state.style,
                image_path=state.image_path,
            )
            state.current_blend_artifact_id = state.session.current_blend_artifact_id
        else:
            state.session = api.start_session(
                prompt=state.prompt,
                mode=state.mode,
                style=state.style,
                image_path=state.image_path,
            )
        show(state.session.message)
    else:
        log("Resuming existing session...")
        show(
            f"Resuming build {state.session.generation_id if state.session else 'unknown'}"
        )

    # Update output_dir to use server-side generation_id if not already set
    if state.session and state.session.generation_id and not state.output_dir:
        state.output_dir = os.path.join(
            config.get("output.default_dir"), state.session.generation_id
        )
        os.makedirs(state.output_dir, exist_ok=True)

    # Show build_id and output_dir early so user can reference them
    if state.session and state.session.generation_id:
        log(f"Build ID: {state.session.generation_id}")
        log(f"Output directory: {state.output_dir}")

    # --- Step loop ---
    revision = 0

    while not state.done:
        try:
            resp: StepResponse = (
                api.editor_step(state.session.generation_id, state)
                if state.workflow == "edit"
                else api.step(state.session.generation_id, state)
            )
        except KeyboardInterrupt:
            log("Cancellation requested by user")
            try:
                api.cancel_session(state.session.generation_id)
            except Exception:
                pass
            state.error = "Cancelled by user"
            state.done = True
            break
        except Exception as e:
            log(f"ERROR: Step request failed: {e}")
            try:
                api.fail_session(
                    state.session.generation_id,
                    f"Client step request failed: {e}",
                )
            except Exception:
                pass
            state.error = str(e)
            state.done = True
            break

        show(resp.message)
        log(f"Action: {resp.action}")

        match resp.action:
            case "error":
                error_msg = resp.data.get("error_message", "Unknown server error")
                log(f"ERROR: Server reported error: {error_msg}")
                state.error = error_msg
                state.done = True
                break

            case "update_code":
                state.code = resp.code
                if state.workflow == "edit":
                    state.edit_code = resp.code
                state.current_blend_artifact_id = resp.data.get(
                    "current_blend_artifact_id", state.current_blend_artifact_id
                )
                state.images = []
                state.last_error = None
                revision += 1

            case "execute":
                if not resp.code:
                    log("ERROR: No script to execute")
                    state.done = True
                    break
                blender_path = config.get_blender_path()
                is_editor = state.workflow == "edit"
                should_save_blend = bool(resp.data.get("save_blend", is_editor))
                script_to_run = resp.code
                if is_editor and state.blend_file and should_save_blend:
                    # Append the save command to the same script so it runs in
                    # the same Blender process that applied the edits.
                    script_to_run = (
                        resp.code
                        + f"\nimport bpy\nbpy.ops.wm.save_as_mainfile(filepath={state.blend_file!r}, compress=True)\n"
                    )
                result = run_blender_script_local(
                    script_to_run,
                    blender_path=blender_path,
                    timeout=resp.data.get("timeout", 120),
                    blend_file_path=state.blend_file if is_editor else None,
                    is_editor_mode=is_editor or None,
                )
                if result.get("error"):
                    state.last_error = result["error"]
                    log(f"Execution error: {state.last_error}")
                else:
                    state.last_output = result.get("output", "")
                    state.last_error = None
                    if is_editor and state.blend_file and should_save_blend:
                        log("Edited .blend saved locally")
                    log("Script executed successfully")

            case "render":
                if not resp.render_scripts:
                    log("ERROR: No render scripts provided")
                    state.done = True
                    break
                prefix = resp.data.get("prefix", "render")
                is_editor = state.workflow == "edit"
                image_paths, error = render_views(
                    resp.render_scripts,
                    state.output_dir,
                    prefix=prefix,
                    revision=revision,
                    blend_file_path=state.blend_file if is_editor else None,
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
                        export_blender_file_local(
                            state.code,
                            generation_id,
                            filename=blend_filename,
                            blend_file_path=state.blend_file if is_editor else None,
                            is_editor_mode=is_editor or None,
                        )
                        log(f"Saved .blend snapshot: {blend_filename}")
                    except Exception as e:
                        log(f"Warning: could not save .blend snapshot: {e}")

            case "done":
                state.done = True

            case _:
                log(f"Unrecognised action '{resp.action}' — skipping")

    # --- End session ---
    if state.error:
        log(f"Session ended with error: {state.error}")
    else:
        log("Ending session...")
        try:
            api.end_session(state.session.generation_id)
            log("Session ended successfully.")
        except Exception as e:
            log(f"Warning: Failed to end session cleanly: {e}")

    return state
