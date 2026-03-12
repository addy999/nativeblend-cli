#!/usr/bin/env python3
"""
NativeBlend CLI - Build 3D models in Blender using natural language prompts
"""

import os

import typer
import base64
import mimetypes
from pathlib import Path as FilePath
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import json as json_lib
from typing import Optional
from .config import config
from .api_client import APIClient
from .executor import (
    run_blender_script_local,
    export_blender_file_local,
    export_glb_local,
    check_blender_exists,
)

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


@app.callback()
def main():
    """Native Blend CLI - Build 3D models in Blender using natural language prompts"""
    pass


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
        table.add_row("Blender Path", config.get("generation.blender_path"))

        console.print(table)

        console.print(
            "\n[green]✓[/green]Run 'nativeblend auth login' to authenticate with your API key"
        )

        # Check if Blender exists
        blender_path = config.get("generation.blender_path")
        console.print(f"\n[bold]Checking Blender installation...[/bold]")

        if not check_blender_exists(blender_path):
            console.print()
            prompt_blender_download()
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] Blender found at: {blender_path}")

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
        api_key = typer.prompt(
            "Enter your NativeBlend API key", hide_input=True
        ).strip()

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
    mode: str = typer.Option(
        None,
        "--mode",
        "-m",
        help="Build mode: 'express' (fast), 'standard' (balanced), 'pro' (high quality)",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
):
    """
    Build a 3D model from a natural language prompt.

    Examples:
        nativeblend build "a low-poly red cube"
        nativeblend build "a racing car" --mode pro
        nativeblend build "a spaceship" --image reference.jpg
    """

    # Check authentication
    api_key = config.get_api_key()
    if not api_key:
        console.print(
            "[red]✗[/red] Not authenticated. Run 'nativeblend auth login' first."
        )
        raise typer.Exit(1)

    # Test blender
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
    # Use default mode from config if not specified
    if not mode:
        mode = config.get("generation.default_mode", "standard")

    # Validate mode
    valid_modes = ["express", "standard", "pro"]
    if mode not in valid_modes:
        console.print(f"[red]✗[/red] Invalid mode: {mode}")
        console.print(f"[dim]Valid modes are: {', '.join(valid_modes)}[/dim]")
        raise typer.Exit(1)

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

    # Initialize API client
    client = APIClient()

    # Submit build request
    console.print("[cyan]→[/cyan] Submitting build request...")
    result = client.submit_generation(
        prompt=prompt,
        image_url=resolved_image_url,
        mode=mode,
    )

    if not result or "error" in result:
        error_msg = result.get("error") if result else "Unknown error"
        console.print(f"[red]✗[/red] Failed to submit build request: {error_msg}")
        raise typer.Exit(1)

    generation_id = result["generation_id"]
    console.print(f"[green]✓[/green] Build started (ID: [cyan]{generation_id}[/cyan])")

    output_path = os.path.join(config.get("output.default_dir"), generation_id)
    console.print(
        f"[dim]You can view progress files and renders in:[/dim] [cyan]{output_path}/[/cyan]"
    )
    os.makedirs(output_path, exist_ok=True)

    # Inline task execution: check for and run Blender tasks during log streaming
    blender_path = config.get_blender_path()

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

            if task_error:
                console.print(f"[yellow]⚠[/yellow] {label} failed: {task_error}")
            else:
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
            console.print(f"[red]✗[/red] {label} failed: {e}")
            try:
                client.completed(task_id, status="failed", error=str(e))
            except Exception:
                pass

    _executing_tasks = False

    def check_and_execute_tasks() -> None:
        """Check for pending tasks and execute them inline.

        Loops until the server has no more pending tasks, so that tasks
        created while Blender is running are never silently dropped.
        A re-entrancy guard prevents double-claiming if a WebSocket message
        arrives while we are already inside this function.
        """
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
                on_check_tasks=check_and_execute_tasks,
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

    # Get final result
    if task_status == "SUCCESS":
        console.print("[cyan]→[/cyan] Fetching build result...")
        final_result = client.get_generation_result(generation_id)

        if not final_result:
            console.print("[red]✗[/red] Failed to fetch build result")
            raise typer.Exit(1)

        code: str = final_result.get("code")
        elapsed_time = final_result.get("elapsed_time", 0)

        console.print(f"[cyan]→[/cyan] Building Blender file...")
        blender_path = export_blender_file_local(code, generation_id)
        console.print(f"[green]✓[/green] Blender file saved to: {blender_path}")

        console.print(f"[cyan]→[/cyan] Building model file...")
        model_path = export_glb_local(code, generation_id)
        console.print(f"[green]✓[/green] Model file saved to: {model_path}")

        # Show success message
        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Model build completed![/bold green]\n\n"
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Mode:[/bold] {mode}\n"
                f"[bold]Build ID:[/bold] {generation_id}\n"
                f"[bold]Elapsed time:[/bold] {elapsed_time:.1f}s\n\n"
                f"[dim]View your model at: https://nativeblend.app/build?generationId={generation_id}[/dim]",
                title="Success",
                border_style="green",
            )
        )

    elif task_status == "FAILURE":
        # TODO: Fetch error details from API and display them here
        console.print(
            Panel(
                "[bold red]✗ Model build failed[/bold red]\n\n"
                f"[bold]Build ID:[/bold] {generation_id}\n"
                f"[dim]Check the web app for error details[/dim]",
                title="Failed",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    elif task_status == "REVOKED":
        console.print("[yellow]⚠[/yellow] Build was cancelled or timed out.")
        raise typer.Exit(1)
