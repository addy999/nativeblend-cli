"""Worker manager for executing Blender tasks from NativeBlend API"""

import os
import sys
import time
import signal
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add the parent directory to the path to import executor
cli_root = Path(__file__).parent.parent.parent
if str(cli_root) not in sys.path:
    sys.path.insert(0, str(cli_root))

from .executor import run_blender_script_local
from .api_client import APIClient
from .config import config

console = Console()


class WorkerStats:
    """Track worker statistics"""

    def __init__(self):
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.tasks_in_progress = 0
        self.lock = threading.Lock()

    def increment_completed(self):
        with self.lock:
            self.tasks_completed += 1
            self.tasks_in_progress -= 1

    def increment_failed(self):
        with self.lock:
            self.tasks_failed += 1
            self.tasks_in_progress -= 1

    def increment_in_progress(self):
        with self.lock:
            self.tasks_in_progress += 1

    def get_stats(self):
        with self.lock:
            return {
                "completed": self.tasks_completed,
                "failed": self.tasks_failed,
                "in_progress": self.tasks_in_progress,
            }


class WorkerManager:
    """Manages background workers that execute Blender tasks"""

    def __init__(self, num_workers: int = 1, poll_interval: int = 5):
        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self.running = False
        self.executor: Optional[ThreadPoolExecutor] = None
        self.api_client = APIClient()
        self.stats = WorkerStats()
        self.futures: set[Future] = set()

        # Check if Blender is available
        console.print("[dim]Setting up Blender...[/dim]")
        self.blender_path = config.get_blender_path()
        if not self.blender_path:
            raise ValueError(
                "Blender path not configured. "
                "Set it with: nativeblend config set generation.blender_path /path/to/blender"
            )
        if not os.path.exists(self.blender_path):
            raise FileNotFoundError(f"Blender not found at: {self.blender_path}")

    def setup(self):
        # Test integration
        test_script = """import bpy
print("Hello from Blender!")
"""
        try:
            result = run_blender_script_local(
                test_script,
                timeout=30,
                blender_path=self.blender_path,
            )
            if result.get("error"):
                raise RuntimeError(f"Blender test script error: {result['error']}")
        except Exception as e:
            raise RuntimeError(f"Failed to execute Blender test script: {str(e)}")

    def process_task(self, task):
        """Process a single task"""
        task_id = task.get("id")
        console.print(f"[cyan]Processing task {task_id}...[/cyan]")

        # Claim the task
        task_data = self.api_client.claim_task(task_id)
        if not task_data:
            console.print(f"[red]Failed to claim task {task_id}[/red]")
            self.stats.increment_failed()
            return

        code = task_data.get("code", "")
        artifact_path = task_data.get("artifact_path", "")
        self.stats.increment_in_progress()
        console.print(f"[dim]Executing Blender script for task {task_id}...[/dim]")

        try:
            # replace artifact_path with a local path instead of the API path, so that the script can save to it directly
            if artifact_path:
                filename = os.path.basename(artifact_path)
                new_artifact_path = os.path.join(
                    config.get("output.default_dir"), task_id, filename
                )

                result = run_blender_script_local(
                    code.replace(artifact_path, new_artifact_path),
                    timeout=120,
                    blender_path=self.blender_path,
                    artifact_path=new_artifact_path,
                )
            else:
                result = run_blender_script_local(
                    code,
                    timeout=120,
                    blender_path=self.blender_path,
                )

            # Determine status and collect fields
            task_status = "failed" if result.get("error") else "completed"
            task_output = result.get("output", "")
            task_error = result.get("error")

            if task_error:
                console.print(
                    f"[red]Error processing task {task_id}: {task_error}[/red]"
                )
            else:
                console.print(f"[green]✓ Task {task_id} completed successfully[/green]")

            console.print(f"[dim]Artifact path: {result.get('artifact_path')}[/dim]")

            artifact_file = None
            if result.get("artifact_path"):
                artifact_file = open(result["artifact_path"], "rb")

            # Submit the result
            if self.api_client.completed(
                task_id,
                status=task_status,
                output=task_output,
                error=task_error,
                artifact=artifact_file,
            ):
                self.stats.increment_completed()
            else:
                console.print(f"[red]Failed to submit result for task {task_id}[/red]")
                self.stats.increment_failed()

            # Cleanup after upload
            # TODO: Check if config.save_renders is enabled, and only delete if it's not and not an image
            if result.get("artifact_path"):
                os.remove(result["artifact_path"])

        except Exception as e:
            console.print(f"[red]Error processing task {task_id}: {e}[/red]")
            self.api_client.completed(task_id, status="failed", error=str(e))
            self.stats.increment_failed()

    def poll_and_execute(self):
        """Poll for tasks and execute them"""
        while self.running:
            try:
                # Get pending tasks
                tasks = self.api_client.list_pending_tasks()

                if tasks and len(tasks) > 0 and self.executor:
                    # Submit tasks to executor
                    for task in tasks:
                        if not self.running:
                            break
                        future = self.executor.submit(self.process_task, task)
                        self.futures.add(future)
                        # Clean up completed futures
                        self.futures = {f for f in self.futures if not f.done()}

                # Wait before polling again
                time.sleep(self.poll_interval)

            except Exception as e:
                console.print(f"[red]Error in polling loop: {e}[/red]")
                time.sleep(self.poll_interval)

    # TODO: allow it to run in background
    def start(self):
        """Start the worker manager"""
        if self.running:
            console.print("[yellow]Workers are already running[/yellow]")
            return

        console.print(
            Panel(
                f"[green]Starting {self.num_workers} worker(s)[/green]\n"
                f"Poll interval: {self.poll_interval}s\n"
                f"Press Ctrl+C to stop",
                title="Worker Manager",
                border_style="green",
            )
        )

        self.running = True
        self.executor = ThreadPoolExecutor(max_workers=self.num_workers)

        # Set up signal handlers for graceful shutdown
        def signal_handler(_signum, _frame):
            console.print("\n[yellow]Shutting down workers...[/yellow]")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start polling in main thread
        try:
            self.poll_and_execute()
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down workers...[/yellow]")
            self.stop()

    def stop(self):
        """Stop the worker manager"""
        if not self.running:
            console.print("[yellow]Workers are not running[/yellow]")
            return

        self.running = False

        if self.executor:
            console.print("[dim]Waiting for tasks to complete...[/dim]")
            self.executor.shutdown(wait=True)

        stats = self.stats.get_stats()
        console.print(
            Panel(
                f"[green]Workers stopped[/green]\n\n"
                f"Tasks completed: {stats['completed']}\n"
                f"Tasks failed: {stats['failed']}\n"
                f"Tasks in progress: {stats['in_progress']}",
                title="Worker Statistics",
                border_style="cyan",
            )
        )

    def get_status(self):
        """Get current worker status"""
        stats = self.stats.get_stats()

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Metric")
        table.add_column("Value")

        table.add_row(
            "Status", "[green]Running[/green]" if self.running else "[red]Stopped[/red]"
        )
        table.add_row("Workers", str(self.num_workers))
        table.add_row("Poll Interval", f"{self.poll_interval}s")
        table.add_row("Tasks Completed", str(stats["completed"]))
        table.add_row("Tasks Failed", str(stats["failed"]))
        table.add_row("Tasks In Progress", str(stats["in_progress"]))

        console.print(
            Panel(
                table,
                title="Worker Status",
                border_style="cyan",
            )
        )
