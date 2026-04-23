"""Render pipeline: executes Blender render scripts and returns image paths.

Each render script is a self-contained Blender Python script (camera, lighting,
wireframe config, render settings). This module executes them locally in
headless Blender and collects the output images.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..executor import run_blender_script_local
from ..config import config


def render_blender_script(
    script: str,
    output_path: str,
) -> dict:
    """Run a complete render script in Blender and return the output image path.

    Args:
        script: Complete Blender Python script (includes camera, lighting,
                and render settings).
        output_path: Where to save the rendered image.

    Returns:
        {"path": str} on success, {"error": str} on failure.
    """
    output_path = os.path.abspath(output_path)
    blender_path = config.get_blender_path()
    result = run_blender_script_local(
        script, blender_path=blender_path, artifact_path=output_path, timeout=120,
    )

    if result.get("error"):
        return {"error": result["error"]}

    if not os.path.exists(output_path):
        return {"error": "Rendering failed, no output image found."}

    return {"path": output_path}


def render_views(
    scripts: list[str],
    output_dir: str,
    *,
    prefix: str = "render",
    revision: int = 1,
) -> tuple[list[str], Optional[str]]:
    """Run a list of complete render scripts in parallel.

    Each script in the list is a fully self-contained Blender Python script
    (camera setup, lighting, render settings). The function assigns output
    paths sequentially and runs them in parallel.

    Args:
        scripts: List of complete Blender render scripts (one per view).
        output_dir: Directory for rendered images.
        prefix: Filename prefix (e.g. "geometry", "material").
        revision: Current revision number for filename.

    Returns:
        (image_paths, error_message). error_message is None on success.
    """
    if not scripts:
        return [], "No render scripts provided."

    os.makedirs(output_dir, exist_ok=True)

    # Build (script, output_path) pairs
    pairs = []
    for i, script in enumerate(scripts):
        filename = f"{prefix}-{revision}-{i}.png" if len(scripts) > 1 else f"{prefix}-{revision}.png"
        pairs.append((script, os.path.join(output_dir, filename)))

    def _render(pair: tuple[str, str]) -> dict:
        script, path = pair
        return render_blender_script(script, path)

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
