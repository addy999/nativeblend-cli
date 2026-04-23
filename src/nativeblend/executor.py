import os
import re
import subprocess
import tempfile
from typing import Optional

import typer
from .config import config

# Patterns that should never appear in a Blender generation script.
# This is a tripwire, not a sandbox: it catches accidents, not attacks.
_BLOCKED_PATTERNS = [
    (r'\bos\.system\b', "os.system call"),
    (r'\bsubprocess\b', "subprocess usage"),
    (r'\bshutil\.rmtree\b', "recursive delete"),
    (r'\bshutil\.move\b', "file move"),
    (r'\b__import__\b', "dynamic import"),
    (r'\beval\s*\(', "eval call"),
    (r'\bexec\s*\(', "exec call"),
    (r'\bcompile\s*\(', "compile call"),
    (r'\bimport\s+socket\b', "socket import"),
    (r'\bimport\s+http\b', "http import"),
    (r'\bimport\s+urllib\b', "urllib import"),
    (r'\bimport\s+requests\b', "requests import"),
    (r'\bimport\s+ctypes\b', "ctypes import"),
    (r'\bimport\s+multiprocessing\b', "multiprocessing import"),
    (r'\bopen\s*\(.*(\/etc|\/usr|\/var|~)', "file access outside working directory"),
    (r'rm\s+-rf', "rm -rf command"),
]


def _check_script_safety(script: str) -> Optional[str]:
    """Check a Blender script for dangerous patterns.

    Returns None if safe, or a description of the violation if blocked.
    """
    for pattern, description in _BLOCKED_PATTERNS:
        if re.search(pattern, script):
            return f"Blocked: script contains {description}"
    return None


def check_blender_exists(blender_path: str) -> bool:
    """
    Check if Blender executable exists at the given path.
    Returns True if exists, False otherwise.
    """
    return os.path.exists(blender_path)


def prompt_blender_download():
    """Display error message and Blender download link."""
    from .main import console
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold red]✗ Blender not found[/bold red]\n\n"
            "NativeBlend CLI requires Blender to be installed on your system.\n\n"
            "[bold]Download Blender:[/bold]\n"
            "🔗 https://www.blender.org/download/\n\n"
            "[dim]After installing, run:[/dim]\n"
            "  nativeblend config set generation.blender_path /path/to/blender",
            title="Blender Required",
            border_style="red",
        )
    )


def _normalize_blender_script(script: str) -> str:
    """
    Normalize Blender script code to fix common issues:
    - Remove unwanted line breaks in assignments (e.g., '= \\nos.path.abspath' -> '= os.path.abspath')
    - Fix broken function calls and assignments
    """
    # Fix line breaks after assignment operators (=, +=, -=, etc.)
    # Pattern: assignment operator followed by newline and then a non-whitespace character
    script = re.sub(r"(?<!=)([+\-*/]?=)(?!=)\s*\n\s*([a-zA-Z_])", r"\1 \2", script)

    return script


def run_blender_script_local(
    script_code: str,
    blender_path: str,
    artifact_path: str | None = None,
    timeout: int = 60,
) -> dict:
    """Execute a Blender script in the current process using a temporary file."""

    safety_violation = _check_script_safety(script_code)
    if safety_violation:
        return {"error": safety_violation}

    blender_path = config.get_blender_path()
    if not check_blender_exists(blender_path):
        prompt_blender_download()
        raise typer.Exit(1)

    # Normalize the script code
    normalized_script = script_code.replace(
        "bpy.ops.wm.read_factory_settings(use_empty=True)", ""
    ).strip()
    normalized_script = _normalize_blender_script(normalized_script)

    full_script_code = f"""
import bpy
import os

scene = bpy.context.scene
if scene.world is None:
    new_world = bpy.data.worlds.new("New World")
    scene.world = new_world

# Delete only mesh objects, keep cameras and lights
bpy.ops.object.select_all(action='DESELECT')
for obj in bpy.context.scene.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
    else:
        obj.select_set(False)
bpy.ops.object.delete()

# --- Your script starts here ---
{normalized_script}
# --- Your script ends here ---
"""

    # Create a temporary file for the script
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
        temp_file.write(full_script_code)
        temp_file_path = temp_file.name

    if artifact_path:
        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)

    try:
        command = [
            blender_path,
            "--background",
            "--factory-startup",  # Disable all add-ons and user preferences
            "--python",
            temp_file_path,
        ]

        result = subprocess.check_output(
            command,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        os.remove(temp_file_path)

        # Check for errors in the output
        error_start = result.find("\nTraceback")
        error_end = result.find("\nBlender quit")

        if error_start != -1:
            error_end = (
                result.find("\nBlender quit", error_start)
                if error_end != -1
                else len(result)
            )
            return {"error": result[error_start:error_end]}

        if (
            'File "' in result
            and "line" in result
            and ("Error" in result or "Exception" in result)
        ):

            return {"error": result}

        # Check if artifact file exists
        if artifact_path:
            if os.path.exists(artifact_path):
                return {
                    "success": True,
                    "output": result,
                    "artifact_path": artifact_path,
                }
            else:
                return {
                    "error": f"Blender script executed but artifact not found at {artifact_path}"
                }

        return {"success": True, "output": result, "artifact_path": None}

    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        if "returned non-zero exit status 1" in str(e):
            raise e

        return {"error": f"Error executing Blender script: {str(e)}"}


def export_blender_file_local(
    script_code: str,
    generation_id: str,
    filename: str = "final_output.blend",
) -> str:
    """Executes a Blender Python script and saves the resulting scene as a .blend file."""

    save_path = os.path.abspath(
        os.path.join(
            config.get("output.default_dir"), generation_id, filename
        )
    )
    full_script = f"""{script_code}


# --- Save the scene as a .blend file ---
output_file = os.path.abspath({repr(save_path)})
bpy.ops.wm.save_as_mainfile(filepath=output_file, compress=True)

print(f"Scene saved to {{output_file}}")
"""
    result = run_blender_script_local(
        full_script, config.get_blender_path(), artifact_path=save_path, timeout=300
    )

    if result.get("error"):
        raise Exception(result["error"])

    return save_path


def export_glb_local(
    script_code: str,
    generation_id: str,
    filename: str = "final_output.glb",
) -> str:
    """Executes a Blender Python script and exports the scene as a GLB file."""

    save_path = os.path.abspath(
        os.path.join(
            config.get("output.default_dir"), generation_id, filename
        )
    )
    full_script = f"""{script_code}


# --- Export the scene to GLB ---
output_file = os.path.abspath({repr(save_path)})
bpy.ops.export_scene.gltf(filepath=output_file, export_format='GLB', export_apply=True, export_texcoords=True)

print(f"Scene exported to {{output_file}}")
"""
    result = run_blender_script_local(
        full_script, config.get_blender_path(), artifact_path=save_path, timeout=300
    )

    if result.get("error"):
        raise Exception(result["error"])

    return save_path
