"""Render pipeline: executes Blender scene-setup scripts and returns image paths.

The API sends scene-setup scripts (camera, lighting, render engine config)
without a filepath or render command. This module appends the output path and
render call, then executes them locally in headless Blender.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..executor import run_blender_script_local
from ..config import config


def _finalize_script(scene_script: str, output_path: str) -> str:
    """Append the render filepath and render command to a scene-setup script."""
    return (
        scene_script
        + f"\nbpy.context.scene.render.filepath = os.path.abspath({repr(output_path)})"
        + "\nbpy.ops.render.render(write_still=True)\n"
    )


def render_blender_script(
    scene_script: str,
    output_path: str,
    blend_file_path: str | None = None,
) -> dict:
    """Finalize a scene-setup script with the output path, then execute it.

    Args:
        scene_script: Blender Python script with camera, lighting, and render
            settings but no filepath or render command.
        output_path: Where to save the rendered image.

    Returns:
        {"path": str} on success, {"error": str} on failure.
    """
    output_path = os.path.abspath(output_path)
    final_script = _finalize_script(scene_script, output_path)
    blender_path = config.get_blender_path()
    result = run_blender_script_local(
        final_script,
        blender_path=blender_path,
        artifact_path=output_path,
        timeout=120,
        blend_file_path=blend_file_path,
    )

    if result.get("error"):
        return {"error": result["error"]}

    if not os.path.exists(output_path):
        return {"error": "Rendering failed, no output image found."}

    return {"path": output_path}


def render_views(
    scripts: list[dict],
    output_dir: str,
    *,
    prefix: str = "render",
    revision: int = 1,
    blend_file_path: str | None = None,
) -> tuple[list[str], Optional[str]]:
    """Run a list of scene-setup scripts in parallel.

    Each entry is a dict with "script" (scene-setup code) and "view" (label
    like "front", "back"). This function appends the output filepath and
    render command, then executes in parallel.

    Args:
        scripts: List of {"script": str, "view": str} dicts from the API.
        output_dir: Directory for rendered images.
        prefix: Filename prefix (e.g. "geometry", "material").
        revision: Current revision number for filename.

    Returns:
        (image_paths, error_message). error_message is None on success.
    """
    if not scripts:
        return [], "No render scripts provided."

    os.makedirs(output_dir, exist_ok=True)

    pairs = []
    for entry in scripts:
        view = entry["view"]
        filename = f"{prefix}-{revision}-{view}.png"
        pairs.append((entry["script"], os.path.join(output_dir, filename)))

    def _render(pair: tuple[str, str]) -> dict:
        scene_script, path = pair
        return render_blender_script(scene_script, path, blend_file_path=blend_file_path)

    with ThreadPoolExecutor(max_workers=len(pairs)) as executor:
        futures = {executor.submit(_render, pair): pair for pair in pairs}
        results = [future.result() for future in as_completed(futures)]

    image_paths = []
    error_message = None
    for result in results:
        if result.get("error"):
            error_message = result["error"]
        else:
            image_paths.append(result["path"])

    if len(image_paths) == 0 and error_message:
        return [], error_message

    return image_paths, None
