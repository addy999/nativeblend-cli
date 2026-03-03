import os
import subprocess
import sys
import tempfile


def run_blender_script_local(
    script_code: str,
    blender_path: str,
    artifact_path: str | None = None,
    timeout: int = 60,
) -> dict:
    """Execute a Blender script in the current process using a temporary file."""

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
{script_code.replace("bpy.ops.wm.read_factory_settings(use_empty=True)", "").strip()}
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
        if artifact_path and os.path.exists(artifact_path):
            return {"success": True, "output": result, "artifact": artifact_path}

        return {"success": True, "output": result, "artifact": None}

    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        if "returned non-zero exit status 1" in str(e):
            raise e

        return {"error": f"Error executing Blender script: {str(e)}"}


# if __name__ == "__main__":
#     script_path = sys.argv[1]
#     with open(script_path, "r") as f:
#         script_code = f.read()
#     result = run_blender_script_local(script_code)
#     print(result)
#     if "error" in result:
#         print("Error executing Blender script:")
#         print(result["error"])
#     else:
#         print("Blender script executed successfully:")
#         print(result["output"])
#         if result["artifact"]:
#             print(f"Artifact saved at: {result['artifact']}")
