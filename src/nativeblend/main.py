#!/usr/bin/env python3
"""
NativeBlend CLI - Generate 3D models in Blender using natural language prompts
"""

import typer
import sys
import time
import subprocess
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
from .worker import stop_worker, is_running, get_pid, get_log_file_path, load_status
from datetime import datetime, timedelta

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

# Worker subcommand group
worker_app = typer.Typer(help="Manage background workers for task execution")
app.add_typer(worker_app, name="worker")


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

        # Ask about starting workers
        if typer.confirm(
            "\nWould you like to start background workers now? Without workers, generations will not be processed. You can also start them later with 'nativeblend worker start'",
            default=True,
        ):

            num_workers = typer.prompt(
                "\nHow many workers would you like to start?",
                type=int,
                default=1,
            )

            if num_workers < 1 or num_workers > 10:
                console.print(
                    "[yellow]⚠[/yellow] Number of workers must be between 1 and 10. Using 1."
                )
                num_workers = 1

            # Start workers
            console.print(
                f"\n[cyan]→[/cyan] Starting {num_workers} background worker(s)..."
            )

            try:
                # Check if already running
                if is_running():
                    console.print("[yellow]⚠[/yellow] Workers are already running")
                else:
                    # Start workers via subprocess
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            f"from nativeblend.worker import start_worker; start_worker({num_workers}, 5)",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )

                    # Give it a moment to start
                    time.sleep(1.5)

                    # Verify it started
                    if is_running():
                        pid = get_pid()
                        console.print(
                            f"\n[green]✓[/green] Workers started successfully (PID: {pid})"
                        )
                        console.print(
                            f"[dim]View logs:[/dim] [cyan]nativeblend worker logs[/cyan]"
                        )
                        console.print(
                            f"[dim]Check status:[/dim] [cyan]nativeblend worker status[/cyan]"
                        )
                    else:
                        console.print(
                            "[yellow]⚠[/yellow] Workers may have failed to start"
                        )
                        console.print(
                            "[dim]Check logs with:[/dim] [cyan]nativeblend worker logs[/cyan]"
                        )

            except Exception as e:
                console.print(f"[red]✗[/red] Failed to start workers: {e}")
        else:
            console.print(
                "\n[dim]You can start workers later with:[/dim] [cyan]nativeblend worker start[/cyan]"
            )

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

    try:
        # Stream logs in real-time via WebSocket
        with console.status("[cyan]→[/cyan] Generating..."):

            def handle_log(log_message: str):
                """Callback for each log message"""
                if verbose:
                    console.print(f"[dim]{log_message}[/dim]")
                else:
                    console.print(f"[cyan]→[/cyan] {log_message}")

            task_status = client.stream_generation_logs(generation_id, handle_log)

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

        # Show success message
        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Model generation completed![/bold green]\n\n"
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Mode:[/bold] {mode}\n"
                f"[bold]Generation ID:[/bold] {generation_id}\n"
                f"[bold]Elapsed time:[/bold] {elapsed_time:.1f}s\n\n"
                f"[dim]View your model at: https://nativeblend.app/builds/{generation_id}[/dim]",
                title="Success",
                border_style="green",
            )
        )

    elif task_status == "FAILURE":
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


@worker_app.command("start")
def worker_start(
    workers: int = typer.Option(
        1, "--workers", "-w", help="Number of workers to start", min=1, max=10
    ),
    poll_interval: int = typer.Option(
        5, "--poll-interval", "-p", help="Polling interval in seconds", min=1
    ),
):
    """
    Start background workers to execute Blender tasks.
    Workers will run in the background and poll for pending tasks.
    """

    # Check authentication
    api_key = config.get_api_key()
    if not api_key:
        console.print(
            "[red]✗[/red] Not authenticated. Run 'nativeblend auth login' first."
        )
        raise typer.Exit(1)

    try:
        # Check if already running
        if is_running():
            pid = get_pid()
            console.print("[yellow]⚠[/yellow] Worker service is already running")
            console.print(
                f"[dim]PID: {pid}[/dim]\n"
                "[dim]Run 'nativeblend worker stop' to stop it first[/dim]"
            )
            raise typer.Exit(1)

        # Start the service in background
        console.print(
            f"[cyan]→[/cyan] Starting worker service with {workers} worker(s)..."
        )

        # Fork to start daemon in background

        subprocess.Popen(
            [
                sys.executable,
                "-c",
                f"from nativeblend.worker import start_worker; start_worker({workers}, {poll_interval})",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Give it a moment to start

        time.sleep(1.5)

        # Verify it started
        if is_running():
            pid = get_pid()
            console.print(
                Panel(
                    f"[bold green]✓ Worker service started successfully![/bold green]\n\n"
                    f"[bold]Workers:[/bold] {workers}\n"
                    f"[bold]Poll interval:[/bold] {poll_interval}s\n"
                    f"[bold]PID:[/bold] {pid}\n\n"
                    f"[dim]View logs:[/dim] [cyan]nativeblend worker logs[/cyan]\n"
                    f"[dim]Check status:[/dim] [cyan]nativeblend worker status[/cyan]\n"
                    f"[dim]Stop workers:[/dim] [cyan]nativeblend worker stop[/cyan]",
                    title="Worker Service",
                    border_style="green",
                )
            )
        else:
            console.print(
                "[red]✗[/red] Worker service failed to start\n"
                "[dim]Check logs with:[/dim] [cyan]nativeblend worker logs[/cyan]"
            )
            raise typer.Exit(1)

    except RuntimeError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]✗[/red] Configuration error: {e}")
        raise typer.Exit(1)
    except FileNotFoundError as e:
        console.print(f"[red]✗[/red] {e}")
        console.print(
            "[dim]Configure Blender path with:[/dim]\n"
            "[cyan]nativeblend config set generation.blender_path /path/to/blender[/cyan]"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to start workers: {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)


@worker_app.command("stop")
def worker_stop():
    """Stop running worker service"""

    try:
        if not is_running():
            console.print("[yellow]⚠[/yellow] Worker service is not running")
            raise typer.Exit(0)

        console.print("[cyan]→[/cyan] Stopping worker service...")
        pid = get_pid()

        # Stop the service
        stop_worker()

        console.print(
            Panel(
                f"[bold green]✓ Worker service stopped[/bold green]\n\n"
                f"[bold]PID:[/bold] {pid}\n\n"
                f"[dim]The service was gracefully shut down[/dim]",
                title="Worker Service",
                border_style="green",
            )
        )

    except RuntimeError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to stop workers: {e}")
        raise typer.Exit(1)


@worker_app.command("status")
def worker_status():
    """Show worker status and statistics"""

    try:
        running = is_running()

        # Create status table
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("", style="bold")
        table.add_column("")

        if running:
            pid = get_pid()
            table.add_row("Status", "[green]✓ Running[/green]")
            table.add_row("PID", str(pid))

            # Load stats from file
            stats = load_status()
            if stats:
                # Add stats to table
                if stats.get("start_time"):
                    start_time = datetime.fromisoformat(stats["start_time"])
                    table.add_row("Started", start_time.strftime("%Y-%m-%d %H:%M:%S"))

                uptime_seconds = stats.get("uptime_seconds", 0)
                uptime = str(timedelta(seconds=int(uptime_seconds)))
                table.add_row("Uptime", uptime)

                table.add_row("Tasks Completed", str(stats.get("completed", 0)))
                table.add_row("Tasks Failed", str(stats.get("failed", 0)))
                table.add_row("Tasks In Progress", str(stats.get("in_progress", 0)))

            console.print(
                Panel(
                    table,
                    title="Worker Service Status",
                    border_style="green",
                )
            )
            console.print(
                "\n[dim]View logs:[/dim] [cyan]nativeblend worker logs[/cyan]"
            )
        else:
            table.add_row("Status", "[red]✗ Not running[/red]")
            console.print(
                Panel(
                    table,
                    title="Worker Service Status",
                    border_style="red",
                )
            )
            console.print(
                "\n[dim]Start workers:[/dim] [cyan]nativeblend worker start[/cyan]"
            )

    except Exception as e:
        console.print(f"[red]✗[/red] Failed to get worker status: {e}")
        raise typer.Exit(1)


@worker_app.command("logs")
def worker_logs(
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Follow log output (like tail -f)"
    ),
    lines: int = typer.Option(
        50, "--lines", "-n", help="Number of lines to show from the end"
    ),
):
    """View worker logs"""

    log_file = get_log_file_path()

    if not log_file.exists():
        console.print(
            "[yellow]⚠[/yellow] No log file found\n"
            "[dim]Logs will appear after starting the worker service[/dim]"
        )
        raise typer.Exit(0)

    try:
        if follow:
            # Use tail -f to follow logs
            console.print(
                f"[dim]Following logs from {log_file}[/dim]\n"
                "[dim]Press Ctrl+C to stop[/dim]\n"
            )
            subprocess.run(["tail", "-f", str(log_file)])
        else:
            # Show last N lines
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"[dim]Last {lines} lines from {log_file}:[/dim]\n")
                console.print(result.stdout)
            else:
                console.print(f"[red]✗[/red] Failed to read log file: {result.stderr}")
                raise typer.Exit(1)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped following logs[/dim]")
    except FileNotFoundError:
        console.print(
            "[red]✗[/red] 'tail' command not found\n"
            f"[dim]View logs directly at: {log_file}[/dim]"
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to read logs: {e}")
        raise typer.Exit(1)
