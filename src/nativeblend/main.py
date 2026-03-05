#!/usr/bin/env python3
"""
NativeBlend CLI - Generate 3D models in Blender using natural language prompts
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
from .executor import run_blender_script_local

# Initialize console for rich output
console = Console()

# Main app
app = typer.Typer(
    name="nativeblend",
    help="Generate 3D models in Blender using natural language prompts",
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
    """Native Blend CLI - Generate 3D models in Blender using natural language prompts"""
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
        table.add_row("Default Mode", config.get("generation.default_mode"))
        table.add_row("Blender Path", config.get("generation.blender_path"))

        console.print(table)

        console.print(
            "\n[green]✓[/green]Run 'nativeblend auth login' to authenticate with your API key"
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


@app.command("generate")
def generate(
    prompt: str = typer.Argument(
        help="Natural language description of the 3D model to generate"
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
        help="Generation mode: 'express' (fast), 'standard' (balanced), 'pro' (high quality)",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
):
    """
    Generate a 3D model from a natural language prompt.

    Examples:
        nativeblend generate "a low-poly red cube"
        nativeblend generate "a racing car" --mode pro
        nativeblend generate "a spaceship" --image reference.jpg
    """

    # Check authentication
    api_key = config.get_api_key()
    if not api_key:
        console.print(
            "[red]✗[/red] Not authenticated. Run 'nativeblend auth login' first."
        )
        raise typer.Exit(1)

    # Test blender
    if not os.path.exists(config.get_blender_path()):
        console.print(
            f"[red]✗[/red] Blender executable not found at: {config.get_blender_path()}"
        )
        console.print(
            "[dim]Please set the correct path to your Blender executable using 'nativeblend config set generation.blender_path /path/to/blender'[/dim]"
        )
        raise typer.Exit(1)

    result = run_blender_script_local(
        'import bpy; print("Blender is working")',
        blender_path=config.get_blender_path(),
        timeout=10,
    )
    if "error" in result:
        console.print(f"[red]✗[/red] Failed to test Blender: {result['error']}")
        console.print(
            "[dim]Please ensure Blender is properly installed and the path is correct[/dim]"
        )
        raise typer.Exit(1)

    # Now, let's generate.
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

    if verbose:
        console.print(f"[bold blue]Generating model for prompt:[/bold blue] {prompt}")
        if resolved_image_url:
            console.print(f"[bold blue]Reference image:[/bold blue] {image_url}")
        console.print(f"[bold blue]Mode:[/bold blue] {mode}")

    # Initialize API client
    client = APIClient()

    # Submit generation request
    console.print("[cyan]→[/cyan] Submitting generation request...")
    result = client.submit_generation(
        prompt=prompt,
        image_url=resolved_image_url,
        mode=mode,
    )

    if not result or "error" in result:
        error_msg = result.get("error") if result else "Unknown error"
        console.print(f"[red]✗[/red] Failed to submit generation request: {error_msg}")
        raise typer.Exit(1)

    generation_id = result["generation_id"]
    console.print(
        f"[green]✓[/green] Generation started (ID: [cyan]{generation_id}[/cyan])"
    )

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
        if lower.endswith((".png", ".jpg", ".jpeg")):
            return "Rendering preview"
        return "Processing in Blender"

    def execute_task_inline(task: dict) -> None:
        """Execute a single Blender task inline."""
        task_id = task.get("id")

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
                result = run_blender_script_local(
                    code.replace(artifact_path, new_artifact_path),
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

    def check_and_execute_tasks() -> None:
        """Check for pending tasks and execute them inline"""
        try:
            tasks = client.list_pending_tasks()
            if tasks:
                for task in tasks:
                    execute_task_inline(task)
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Task check error: {e}")

    try:
        # Stream logs in real-time via WebSocket
        with console.status("[cyan]→[/cyan] Generating..."):

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
            f"\n[yellow]⚠[/yellow] Cancelling generation [cyan]{generation_id}[/cyan]..."
        )
        cancelled = client.cancel_generation(generation_id)
        if cancelled:
            console.print(
                f"[yellow]⚠[/yellow] Generation [cyan]{generation_id}[/cyan] has been revoked"
            )
        else:
            console.print(f"[red]✗[/red] Failed to revoke generation {generation_id}")
        raise typer.Exit(1)

    # Get final result
    if task_status == "SUCCESS":
        console.print("[cyan]→[/cyan] Fetching generation result...")
        final_result = client.get_generation_result(generation_id)

        if not final_result:
            console.print("[red]✗[/red] Failed to fetch generation result")
            raise typer.Exit(1)

        elapsed_time = final_result.get("elapsed_time", 0)
        model_file_url = final_result.get("model_file_url")
        blender_file_url = final_result.get("blender_file_url")

        # Download files if URLs are provided and save to output directory
        if model_file_url:
            console.print(f"[cyan]→[/cyan] Downloading model file...")
            model_response = client.download_file(model_file_url)
            if model_response:
                model_path = os.path.join(output_path, "final-model.glb")
                with open(model_path, "wb") as f:
                    f.write(model_response)
                console.print(f"[green]✓[/green] Model file saved to: {model_path}")
            else:
                console.print(f"[yellow]⚠[/yellow] Failed to download model file")

        if blender_file_url:
            console.print(f"[cyan]→[/cyan] Downloading Blender file...")
            blender_response = client.download_file(blender_file_url)
            if blender_response:
                blender_path = os.path.join(output_path, "final-model.blend")
                with open(blender_path, "wb") as f:
                    f.write(blender_response)
                console.print(f"[green]✓[/green] Blender file saved to: {blender_path}")
            else:
                console.print(f"[yellow]⚠[/yellow] Failed to download Blender file")

        # Show success message
        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Model generation completed![/bold green]\n\n"
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Mode:[/bold] {mode}\n"
                f"[bold]Generation ID:[/bold] {generation_id}\n"
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
                "[bold red]✗ Model generation failed[/bold red]\n\n"
                f"[bold]Generation ID:[/bold] {generation_id}\n"
                f"[dim]Check the web app for error details[/dim]",
                title="Failed",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    elif task_status == "REVOKED":
        console.print("[yellow]⚠[/yellow] Generation was cancelled")
        raise typer.Exit(1)
