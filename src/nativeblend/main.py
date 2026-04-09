#!/usr/bin/env python3
"""
NativeBlend CLI - Build 3D models in Blender using natural language prompts
"""

import os
import threading
from enum import Enum

import typer
import base64
import mimetypes
import requests
from pathlib import Path as FilePath
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import json as json_lib
from typing import Optional, Dict, Any
from . import __version__
from .config import config
from .api_client import APIClient
from .executor import (
    run_blender_script_local,
    export_blender_file_local,
    export_glb_local,
    check_blender_exists,
    prompt_blender_download,
)

class BuildMode(str, Enum):
    express = "express"
    standard = "standard"
    pro = "pro"


class BuildStyle(str, Enum):
    auto = "auto"
    low_poly = "low-poly"
    stylized = "stylized"
    semi_realistic = "semi-realistic"
    realistic = "realistic"
    cartoon = "cartoon"
    geometric = "geometric"
    voxel = "voxel"
    retro = "retro"
    pixel_art = "pixel-art"
    gamecube = "gamecube"


# Initialize console for rich output
console = Console()

# Main app
app = typer.Typer(
    name="nativeblend",
    help="Build 3D models in Blender using natural language prompts",
    add_completion=True,
)

# Auth subcommand group
auth_app = typer.Typer(help="Manage authentication and API keys")
app.add_typer(auth_app, name="auth")

# Config subcommand group
config_app = typer.Typer(help="Manage configuration settings")
app.add_typer(config_app, name="config")

# Generations subcommand group
gen_app = typer.Typer(help="Browse and manage generations")
app.add_typer(gen_app, name="generations")


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _check_for_update() -> Optional[str]:
    """Check PyPI for a newer version. Returns the latest version string if newer, else None."""
    try:
        response = requests.get(
            "https://pypi.org/pypi/nativeblend/json",
            timeout=2,
        )
        if response.status_code == 200:
            latest = response.json()["info"]["version"]
            if __version__ != "dev" and _version_tuple(latest) > _version_tuple(
                __version__
            ):
                return latest
    except Exception:
        console.print("[yellow]⚠[/yellow] Update check failed")
    return None


def version_callback(value: bool):
    """Callback for --version flag"""
    if value:
        console.print(f"nativeblend version [cyan]{__version__}[/cyan]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    )
):
    """Native Blend CLI - Build 3D models in Blender using natural language prompts"""
    _result: list = [None]

    def _do_check():
        _result[0] = _check_for_update()

    t = threading.Thread(target=_do_check, daemon=True)
    t.start()
    t.join(timeout=2)

    if _result[0]:
        console.print(
            f"[yellow]A new version of nativeblend is available:[/yellow] "
            f"[dim]{__version__}[/dim] → [cyan bold]{_result[0]}[/cyan bold]\n"
            f"[dim]Run:[/dim] [bold]pip install nativeblend --upgrade[/bold]\n"
        )


@app.command("init")
def init():
    """
    Initialize NativeBlend CLI configuration.
    Creates config directory and file with default settings.
    """
    try:
        config.initialize()
        console.print(
            f"[green]✓[/green] Configuration initialized at: {config.config_file}"
        )
        console.print("\n[bold]Default settings:[/bold]")

        # Display current config
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Setting")
        table.add_column("Value")

        table.add_row("API Endpoint", config.get("api.endpoint"))
        table.add_row("API Timeout", f"{config.get('api.timeout')}s")
        table.add_row("Default Output Dir", config.get("output.default_dir"))
        table.add_row("Save Renders", str(config.get("output.save_renders")))
        table.add_row("Default Build Mode", config.get("generation.default_mode"))
        table.add_row("Default Style", config.get("generation.default_style"))
        if config.is_local_blender():
            table.add_row("Blender Path", config.get("generation.blender_path"))

        console.print(table)

        console.print(
            "\n[green]✓[/green]Run 'nativeblend auth login' to authenticate with your API key"
        )

        # Check if Blender exists (only when local_blender is enabled)
        if config.is_local_blender():
            blender_path = config.get("generation.blender_path")
            console.print(f"\n[bold]Checking Blender installation...[/bold]")

            if not check_blender_exists(blender_path):
                console.print()
                prompt_blender_download()
                raise typer.Exit(1)

            console.print(f"[green]✓[/green] Blender found at: {blender_path}")

        # Check authentication status
        console.print(f"\n[bold]Checking authentication...[/bold]")
        api_key = config.get_api_key()
        authenticated = False
        if api_key:
            client = APIClient(api_key=api_key)
            if client.validate_api_key():
                console.print(
                    f"[green]✓[/green] Authenticated (key: {api_key[:8]}...{api_key[-4:]})"
                )
                authenticated = True
            else:
                console.print(
                    "[yellow]⚠[/yellow] Stored API key is invalid or the API is unreachable"
                )
        else:
            console.print("[yellow]⚠[/yellow] No API key configured")

        if not authenticated:
            console.print("[dim]Enter your API key to authenticate now, or press Enter to skip[/dim]")
            new_key = typer.prompt("NativeBlend API key", default="", show_default=False).strip()
            if new_key:
                client = APIClient(api_key=new_key)
                if client.validate_api_key():
                    config.set_api_key(new_key)
                    console.print("[green]✓[/green] Successfully authenticated!")
                    console.print(
                        "[dim]Your API key has been securely stored in the system keychain[/dim]"
                    )
                else:
                    console.print(
                        "[red]✗[/red] Invalid API key — run 'nativeblend auth login' to try again"
                    )
            else:
                console.print(
                    "[dim]Skipped — run 'nativeblend auth login' to authenticate later[/dim]"
                )

    except Exception as e:
        console.print(f"[red]✗[/red] Failed to initialize config: {e}")
        raise typer.Exit(1)


@auth_app.command("login")
def auth_login(
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", help="API key (will prompt if not provided)"
    )
):
    """
    Login with your NativeBlend API key.
    Get your API key from https://nativeblend.app/auth
    """
    # Ensure config is initialized
    config.initialize()

    # Get API key from user if not provided
    if not api_key:
        api_key = typer.prompt("Enter your NativeBlend API key").strip()

    if not api_key:
        console.print("[red]✗[/red] API key cannot be empty")
        raise typer.Exit(1)

    # Validate the API key
    console.print("[dim]Validating API key...[/dim]")
    client = APIClient(api_key=api_key)

    if not client.validate_api_key():
        console.print("[red]✗[/red] Invalid API key or unable to connect to API")
        console.print("[dim]Please check your API key and internet connection[/dim]")
        raise typer.Exit(1)

    # Save the API key
    config.set_api_key(api_key)

    console.print("[green]✓[/green] Successfully authenticated!")
    console.print(
        "[dim]Your API key has been securely stored in the system keychain[/dim]"
    )


@auth_app.command("status")
def auth_status():
    """Check authentication status and API connection"""
    api_key = config.get_api_key()

    if not api_key:
        console.print(
            Panel(
                "[yellow]Not authenticated[/yellow]\n\n"
                "Run 'nativeblend auth login' to authenticate",
                title="Authentication Status",
                border_style="yellow",
            )
        )
        raise typer.Exit(1)

    # Check if API key is valid
    console.print("[dim]Checking API connection...[/dim]")
    client = APIClient()
    if client.validate_api_key():
        # Create status table
        table = Table(show_header=False, box=None)
        table.add_column("", style="bold")
        table.add_column("")

        table.add_row("Status", "[green]✓ Authenticated[/green]")
        table.add_row("API Endpoint", config.get_api_endpoint())
        table.add_row("API Key", f"{api_key[:8]}...{api_key[-4:]}")

        console.print(
            Panel(
                table,
                title="Authentication Status",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[red]Authentication failed[/red]\n\n"
                "Your API key appears to be invalid or the API is unreachable.\n"
                "Run 'nativeblend auth login' to re-authenticate",
                title="Authentication Status",
                border_style="red",
            )
        )
        raise typer.Exit(1)


@auth_app.command("logout")
def auth_logout():
    """Logout and remove stored API key"""
    api_key = config.get_api_key()

    if not api_key:
        console.print("[yellow]⚠[/yellow] You are not currently logged in")
        raise typer.Exit(0)

    # Confirm logout
    if not typer.confirm("Are you sure you want to logout?"):
        console.print("[dim]Logout cancelled[/dim]")
        raise typer.Exit(0)

    # Delete the API key
    config.delete_api_key()
    console.print("[green]✓[/green] Successfully logged out")
    console.print("[dim]Your API key has been removed from the system keychain[/dim]")


@config_app.command("show")
def config_show():
    """Show current configuration"""
    console.print(f"\n[bold]Configuration file:[/bold] {config.config_file}\n")

    # Create a table for config values
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting")
    table.add_column("Value")

    # Flatten config and display
    def add_rows(data: dict, prefix: str = ""):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                add_rows(value, full_key)
            else:
                table.add_row(full_key, str(value))

    add_rows(config._data)
    console.print(table)

    # Show API key status
    api_key = config.get_api_key()
    if api_key:
        console.print(
            f"\n[dim]API Key: {api_key[:8]}...{api_key[-4:]} (stored in keychain)[/dim]"
        )
    else:
        console.print("\n[dim]API Key: Not configured[/dim]")


@config_app.command("get")
def config_get(key: str):
    """Get a configuration value (e.g., 'api.endpoint')"""
    value = config.get(key)
    if value is not None:
        console.print(f"[cyan]{key}[/cyan] = {value}")
    else:
        console.print(f"[red]✗[/red] Setting '{key}' not found")
        raise typer.Exit(1)


@config_app.command("set")
def config_set(key: str, value: str):
    """
    Set a configuration value (e.g., 'api.endpoint' 'https://api.example.com')
    """
    try:
        # Try to parse as JSON for booleans/numbers

        try:
            parsed_value = json_lib.loads(value)
        except json_lib.JSONDecodeError:
            # If not valid JSON, treat as string
            parsed_value = value

        config.set(key, parsed_value)
        console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan] = {parsed_value}")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to set config: {e}")
        raise typer.Exit(1)


@app.command("build")
def build(
    prompt: str = typer.Argument(
        help="Natural language description of the 3D model to build"
    ),
    image_url: Optional[str] = typer.Option(
        None,
        "--image",
        "-i",
        help="URL or local path to reference image for the 3D model",
    ),
    mode: Optional[BuildMode] = typer.Option(
        None,
        "--mode",
        "-m",
        help="Build mode (default: from config or 'standard')",
    ),
    style: Optional[BuildStyle] = typer.Option(
        None,
        "--style",
        "-s",
        help="Visual style (default: from config or 'auto')",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
):
    """
    Build a 3D model from a natural language prompt.

    Examples:
        nativeblend build "a car"
        nativeblend build "a car" --style low-poly
        nativeblend build "a racing car" --mode pro --style realistic
        nativeblend build "a spaceship" --image reference.jpg --style cartoon
    """

    # Check authentication
    api_key = config.get_api_key()
    if not api_key:
        console.print(
            "[red]✗[/red] Not authenticated. Run 'nativeblend auth login' first."
        )
        raise typer.Exit(1)

    # Test blender (only when local_blender is enabled)
    local_blender = config.is_local_blender()
    if local_blender:
        blender_path = config.get_blender_path()
        if not check_blender_exists(blender_path):
            prompt_blender_download()
            raise typer.Exit(1)

        result = run_blender_script_local(
            'import bpy; print("Blender is working")',
            blender_path=blender_path,
            timeout=10,
        )
        if "error" in result:
            console.print(f"[red]✗[/red] Failed to test Blender: {result['error']}")
            console.print(
                "[dim]Please ensure Blender is properly installed and the path is correct[/dim]"
            )
            raise typer.Exit(1)

    # Now, let's build.
    # Fall back to config defaults when not provided on the CLI
    if mode is None:
        mode = BuildMode(config.get("generation.default_mode", BuildMode.standard))
    if style is None:
        style = BuildStyle(config.get("generation.default_style", BuildStyle.auto))

    # Resolve local image path to base64 data URL if needed
    resolved_image_url = image_url
    if image_url and FilePath(image_url).is_file():
        if verbose:
            console.print(f"[cyan]→[/cyan] Converting local image to base64...")
        path = FilePath(image_url)
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/png"
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        resolved_image_url = f"data:{mime_type};base64,{b64}"

    console.print(f"[bold blue]Building model for prompt:[/bold blue] {prompt}")
    if resolved_image_url:
        console.print(f"[bold blue]Reference image:[/bold blue] {image_url}")
    console.print(f"[bold blue]Mode:[/bold blue] {mode}")
    console.print(f"[bold blue]Style:[/bold blue] {style}")

    # Initialize API client
    client = APIClient()

    # Submit build request
    console.print("[cyan]→[/cyan] Submitting build request...")
    gen_result: Optional[Dict[str, Any]] = client.submit_generation(
        prompt=prompt,
        image_url=resolved_image_url,
        mode=mode,
        style=style,
    )

    if not gen_result or "error" in gen_result:
        error_msg = gen_result.get("error") if gen_result else "Unknown error"
        console.print(f"[red]✗[/red] Failed to submit build request: {error_msg}")
        raise typer.Exit(1)

    generation_id = gen_result["generation_id"]
    console.print(f"[green]✓[/green] Build started (ID: [cyan]{generation_id}[/cyan])")

    output_path = os.path.join(config.get("output.default_dir"), generation_id)
    console.print(
        f"[dim]You can view progress files and renders in:[/dim] [cyan]{output_path}/[/cyan]"
    )
    os.makedirs(output_path, exist_ok=True)

    # Inline task execution: check for and run Blender tasks during log streaming
    blender_path = config.get_blender_path() if local_blender else None

    def _describe_task(artifact_path: str) -> str:
        """Return a human-friendly label based on the artifact file extension."""
        if not artifact_path:
            return "Processing in Blender"
        lower = artifact_path.lower()
        if lower.endswith(".glb") or lower.endswith(".gltf"):
            return "Exporting model"
        if lower.endswith(".blend"):
            return "Saving Blender file"
        if lower.endswith((".png", ".jpg", ".jpeg")) and "behind" not in lower:
            return "Rendering preview"
        return "Processing in Blender"

    def execute_task_inline(task: dict) -> None:
        """Execute a single Blender task inline."""

        task_id = task.get("id")
        assert task_id, "Task must have an ID"

        # Claim the task
        task_data = client.claim_task(task_id)
        if not task_data:
            console.print(f"[yellow]⚠[/yellow] Failed to claim task")
            return

        code = task_data.get("code", "")
        artifact_path = task_data.get("artifact_path", "")
        generation = task_data.get("generation", "")

        if not generation:
            console.print(f"[yellow]⚠[/yellow] Skipping task — missing generation ID")
            return

        label = _describe_task(artifact_path)
        console.print(f"[cyan]→[/cyan] {label}...")

        try:
            # Replace artifact_path with a local path
            if artifact_path:
                filename = os.path.basename(artifact_path)
                new_artifact_path = os.path.abspath(
                    os.path.join(config.get("output.default_dir"), generation, filename)
                )
                # Normalize path to use forward slashes (works on Windows and avoids escape sequence issues)
                new_artifact_path_normalized = new_artifact_path.replace("\\", "/")
                result = run_blender_script_local(
                    code.replace(artifact_path, new_artifact_path_normalized),
                    timeout=120,
                    blender_path=blender_path,
                    artifact_path=new_artifact_path,
                )
            else:
                result = run_blender_script_local(
                    code,
                    timeout=120,
                    blender_path=blender_path,
                )

            task_status_str = "failed" if result.get("error") else "completed"
            task_output = result.get("output", "")
            task_error = result.get("error")

            if task_status_str == "completed":
                nonlocal _executed_local_tasks
                _executed_local_tasks = True

            console.print(f"[green]✓[/green] {label} done")

            # Upload result with artifact
            artifact_file = None
            try:
                if result.get("artifact_path"):
                    artifact_file = open(result["artifact_path"], "rb")

                client.completed(
                    task_id,
                    status=task_status_str,
                    output=task_output,
                    error=task_error,
                    artifact=artifact_file,
                )
            finally:
                if artifact_file:
                    artifact_file.close()

                # Cleanup artifact file (keep .blend files and saved renders)
                if result.get("artifact_path") and os.path.exists(
                    result["artifact_path"]
                ):
                    is_image = (
                        result["artifact_path"]
                        .lower()
                        .endswith((".png", ".jpg", ".jpeg"))
                        and "behind" not in result["artifact_path"].lower()
                    )
                    is_blend_file = result["artifact_path"].lower().endswith(".blend")

                    if is_blend_file or (
                        is_image and config.get("output.save_renders")
                    ):
                        return

                    try:
                        os.remove(result["artifact_path"])
                    except Exception:
                        pass

        except Exception as e:
            try:
                client.completed(task_id, status="failed", error=str(e))
            except Exception:
                pass

            console.print(f"[green]✓[/green] {label} done")

    _executing_tasks = False
    _executed_local_tasks = False

    def check_and_execute_tasks() -> None:
        """Check for pending tasks and execute them inline (local_blender only).

        Loops until the server has no more pending tasks, so that tasks
        created while Blender is running are never silently dropped.
        A re-entrancy guard prevents double-claiming if a WebSocket message
        arrives while we are already inside this function.
        """
        if not local_blender:
            return
        nonlocal _executing_tasks
        if _executing_tasks:
            return
        _executing_tasks = True
        try:
            while True:
                tasks = client.list_pending_tasks(generation_id=generation_id)
                if not tasks:
                    break
                for task in tasks:
                    execute_task_inline(task)
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Task check error: {e}")
        finally:
            _executing_tasks = False

    # Real-time artifact polling: download renders as they're produced on the backend
    _already_downloaded: set = set()

    def check_and_download_artifacts() -> None:
        """Poll for new artifacts and download them to output_path."""
        if _executed_local_tasks:
            return  # Images already saved locally by inline execution
        try:
            artifacts = client.get_generation_artifacts(generation_id)
            if not artifacts:
                return
            for artifact in artifacts:
                name = artifact.get("name", "")
                if name in _already_downloaded:
                    continue
                data = client.download_file(artifact["url"])
                if data:
                    artifact_path = os.path.join(output_path, name)
                    with open(artifact_path, "wb") as f:
                        f.write(data)
                    _already_downloaded.add(name)
                    console.print(f"[green]✓[/green] Saved render: {name}")
        except Exception:
            pass  # Non-blocking — don't interrupt the build

    def on_check_all() -> None:
        """Combined callback: check tasks then poll artifacts."""
        check_and_execute_tasks()
        check_and_download_artifacts()

    try:
        # Stream logs in real-time via WebSocket
        with console.status("[cyan]→[/cyan] Building..."):

            def handle_log(log_message: str):
                """Callback for each log message"""
                if verbose:
                    console.print(f"[dim]{log_message}[/dim]")
                else:
                    console.print(f"[cyan]→[/cyan] {log_message}")

            task_status = client.stream_generation_logs(
                generation_id,
                handle_log,
                on_check_tasks=on_check_all,
            )

        if not task_status:
            console.print("[yellow]⚠[/yellow] Lost connection to log stream")
            # Fall back to checking final status
            status_result = client.get_generation_status(generation_id)
            if status_result:
                task_status = status_result.get("status")

    except KeyboardInterrupt:
        console.print(
            f"\n[yellow]⚠[/yellow] Cancelling build [cyan]{generation_id}[/cyan]..."
        )
        cancelled = client.cancel_generation(generation_id)
        if cancelled:
            console.print(
                f"[yellow]⚠[/yellow] Build [cyan]{generation_id}[/cyan] has been cancelled"
            )
        else:
            console.print(f"[red]✗[/red] Failed to cancel build {generation_id}")
        raise typer.Exit(1)

    # Final artifact poll to catch any last images
    check_and_download_artifacts()

    # Get final result
    if task_status == "SUCCESS":
        console.print("[cyan]→[/cyan] Fetching build result...")
        final_result = client.get_generation_result(generation_id)

        if not final_result:
            console.print("[red]✗[/red] Failed to fetch build result")
            raise typer.Exit(1)

        code = final_result.get("code", "")
        elapsed_time = final_result.get("elapsed_time", 0)

        if local_blender:
            console.print(f"[cyan]→[/cyan] Building Blender file...")
            blender_save_path = export_blender_file_local(code, generation_id)
            console.print(f"[green]✓[/green] Blender file saved to: {blender_save_path}")

            console.print(f"[cyan]→[/cyan] Building model file...")
            model_path = export_glb_local(code, generation_id)
            console.print(f"[green]✓[/green] Model file saved to: {model_path}")
        else:
            console.print(f"[cyan]→[/cyan] Exporting model files...")
            export_result = client.export_generation(generation_id)
            if export_result:
                for key, label, filename in [
                    ("model_url", "Model", "final_output.glb"),
                    ("blender_url", "Blender", "final_output.blend"),
                ]:
                    url = export_result.get(key)
                    if url:
                        data = client.download_file(url)
                        if data:
                            save_path = os.path.join(output_path, filename)
                            with open(save_path, "wb") as f:
                                f.write(data)
                            console.print(f"[green]✓[/green] {label} file saved to: {save_path}")
            else:
                console.print("[yellow]⚠[/yellow] Failed to export files from server")

        # Show success message
        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Model build completed![/bold green]\n\n"
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Mode:[/bold] {mode}\n"
                f"[bold]Style:[/bold] {style}\n"
                f"[bold]Build ID:[/bold] {generation_id}\n"
                f"[bold]Elapsed time:[/bold] {elapsed_time:.1f}s\n\n"
                f"[dim]View your model at: https://nativeblend.app/build?generationId={generation_id}[/dim]",
                title="Success",
                border_style="green",
            )
        )

    elif task_status == "FAILURE":
        console.print(
            Panel(
                "[bold red]✗ Model build failed[/bold red]\n\n"
                f"[bold]Build ID:[/bold] {generation_id}\n"
                f"[dim]Contact support at support@nativeblend.app[/dim]",
                title="Failed",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    elif task_status == "REVOKED":
        console.print("[yellow]⚠[/yellow] Build timed out or was cancelled")
        raise typer.Exit(1)


# ---- Generations subcommands ----


@gen_app.command("list")
def gen_list(
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    per_page: int = typer.Option(20, "--per-page", "-n", help="Items per page"),
):
    """List your generations."""
    client = APIClient()
    result = client.list_generations(page=page, per_page=per_page)

    if not result or not result.get("generations"):
        console.print("[yellow]No generations found[/yellow]")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Prompt", max_width=50)
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Created")

    for gen in result["generations"]:
        status = gen.get("status", "")
        status_style = {
            "SUCCESS": "[green]SUCCESS[/green]",
            "FAILURE": "[red]FAILURE[/red]",
            "PENDING": "[yellow]PENDING[/yellow]",
            "PROCESSING": "[cyan]PROCESSING[/cyan]",
            "REVOKED": "[dim]REVOKED[/dim]",
        }.get(status, status)

        prompt_text = gen.get("prompt", "")
        if len(prompt_text) > 50:
            prompt_text = prompt_text[:47] + "..."

        table.add_row(
            gen["id"],
            prompt_text,
            status_style,
            gen.get("mode", ""),
            gen.get("created", "")[:19],  # Trim timezone
        )

    total = result.get("total", 0)
    total_pages = (total + per_page - 1) // per_page
    console.print(table)
    console.print(
        f"\n[dim]Page {page} of {total_pages} ({total} total)[/dim]"
    )
    if page < total_pages:
        console.print(
            f"[dim]Next page: nativeblend generations list --page {page + 1}[/dim]"
        )


@gen_app.command("download")
def gen_download(
    generation_id: str = typer.Argument(help="Generation ID to download"),
    select: bool = typer.Option(
        False, "--select", "-s", help="Interactively select individual checkpoints"
    ),
):
    """Download model files for a generation.

    By default downloads the final .glb and .blend files. Use --select to
    interactively pick individual build checkpoints instead.
    """
    client = APIClient()
    output_path = os.path.join(config.get("output.default_dir"), generation_id)
    os.makedirs(output_path, exist_ok=True)

    if not select:
        # Default: download the final exported model
        console.print("[cyan]→[/cyan] Exporting final generation output...")
        export_result = client.export_generation(generation_id)

        if not export_result:
            console.print("[yellow]⚠[/yellow] Failed to export generation")
            raise typer.Exit(1)

        if export_result.get("model_url"):
            data = client.download_file(export_result["model_url"])
            if data:
                with open(os.path.join(output_path, "final_output.glb"), "wb") as f:
                    f.write(data)
                console.print("[green]✓[/green] Saved: final_output.glb")

        if export_result.get("blender_url"):
            data = client.download_file(export_result["blender_url"])
            if data:
                with open(os.path.join(output_path, "final_output.blend"), "wb") as f:
                    f.write(data)
                console.print("[green]✓[/green] Saved: final_output.blend")

        console.print(
            f"\n[green]✓[/green] Files saved to: [cyan]{output_path}[/cyan]"
        )
        return

    # --select mode: interactive checkpoint picker
    import questionary

    console.print("[cyan]→[/cyan] Fetching generation data...")
    checkpoints = client.get_generation_checkpoints(generation_id)

    if not checkpoints:
        console.print("[yellow]No checkpoints found for this generation[/yellow]")
        raise typer.Exit()

    # Build choices for multi-select
    choices = []
    for i, cp in enumerate(checkpoints):
        step = cp.get("step", "unknown")
        created = cp.get("created", "")[:19]
        label = f"[{i + 1}] {step} — {created}"
        choices.append(questionary.Choice(title=label, value=i))

    choices.insert(0, questionary.Choice(title="Latest (final output)", value="latest"))
    choices.insert(0, questionary.Choice(title="All checkpoints", value="all"))

    selected = questionary.checkbox(
        "Select checkpoints to download:",
        choices=choices,
    ).ask()

    if not selected:
        console.print("[yellow]No checkpoints selected[/yellow]")
        raise typer.Exit()

    # Handle "latest" — export final generation output
    if "latest" in selected:
        console.print("[cyan]→[/cyan] Exporting final generation output...")
        export_result = client.export_generation(generation_id)
        if export_result:
            if export_result.get("model_url"):
                data = client.download_file(export_result["model_url"])
                if data:
                    with open(os.path.join(output_path, "final_output.glb"), "wb") as f:
                        f.write(data)
                    console.print("[green]✓[/green] Saved: final_output.glb")
            if export_result.get("blender_url"):
                data = client.download_file(export_result["blender_url"])
                if data:
                    with open(os.path.join(output_path, "final_output.blend"), "wb") as f:
                        f.write(data)
                    console.print("[green]✓[/green] Saved: final_output.blend")
        else:
            console.print("[yellow]⚠[/yellow] Failed to export final output")

    # Resolve checkpoint indices
    if "all" in selected:
        indices = list(range(len(checkpoints)))
    else:
        indices = [s for s in selected if isinstance(s, int)]

    # Export and download each selected checkpoint via the backend
    for idx in indices:
        cp = checkpoints[idx]
        step = cp.get("step", "unknown")
        cp_id = cp["id"]

        console.print(f"[cyan]→[/cyan] Exporting checkpoint {idx + 1} ({step})...")
        export_result = client.export_checkpoint(generation_id, cp_id)

        if not export_result:
            console.print(f"[yellow]⚠[/yellow] Failed to export checkpoint {idx + 1}")
            continue

        # Download .glb
        if export_result.get("model_url"):
            data = client.download_file(export_result["model_url"])
            if data:
                filename = f"checkpoint-{step}-{idx + 1}.glb"
                with open(os.path.join(output_path, filename), "wb") as f:
                    f.write(data)
                console.print(f"[green]✓[/green] Saved: {filename}")

        # Download .blend
        if export_result.get("blender_url"):
            data = client.download_file(export_result["blender_url"])
            if data:
                filename = f"checkpoint-{step}-{idx + 1}.blend"
                with open(os.path.join(output_path, filename), "wb") as f:
                    f.write(data)
                console.print(f"[green]✓[/green] Saved: {filename}")

    console.print(
        f"\n[green]✓[/green] Files saved to: [cyan]{output_path}[/cyan]"
    )
