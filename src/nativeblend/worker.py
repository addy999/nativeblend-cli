"""Worker manager for executing Blender tasks from NativeBlend API"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from pyservice import Service
import logging
from logging.handlers import RotatingFileHandler

# Add the parent directory to the path to import executor
cli_root = Path(__file__).parent.parent.parent
if str(cli_root) not in sys.path:
    sys.path.insert(0, str(cli_root))

from .executor import run_blender_script_local
from .api_client import APIClient
from .config import config

# Worker runtime directory
WORKER_DIR = Path.home() / ".nativeblend" / "workers"
WORKER_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = WORKER_DIR / "worker.log"
STATUS_FILE = WORKER_DIR / "status.json"


class WorkerStats:
    """Track worker statistics"""

    def __init__(self):
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.tasks_in_progress = 0
        self.start_time = None
        self.lock = threading.Lock()

    def start(self):
        """Mark worker as started"""
        with self.lock:
            self.start_time = datetime.now()

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
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "uptime_seconds": (
                    (datetime.now() - self.start_time).total_seconds()
                    if self.start_time
                    else 0
                ),
            }

    def save_to_file(self):
        """Save stats to file for status command"""
        try:
            with self.lock:
                stats = self.get_stats()
                with open(STATUS_FILE, "w") as f:
                    json.dump(stats, f, indent=2)
        except Exception:
            pass  # Ignore errors writing status file


class WorkerService(Service):
    """Background service that executes Blender tasks"""

    def __init__(self, num_workers: int = 1, poll_interval: int = 5, *args, **kwargs):
        # Initialize parent with service name and PID directory
        super().__init__("nativeblend-worker", pid_dir=str(WORKER_DIR), *args, **kwargs)

        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self.executor: Optional[ThreadPoolExecutor] = None
        self.api_client = None  # Will be initialized in run()
        self.stats = WorkerStats()
        self.futures: set[Future] = set()
        self.blender_path = None

        # Configure logging to file
        self.logger.setLevel(logging.INFO)

        # Remove any existing handlers
        self.logger.handlers.clear()

        # Add rotating file handler (10MB max, keep 3 backups)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Preserve the log file when daemonizing
        self.files_preserve = [file_handler.stream]

    def setup_environment(self):
        """Setup worker environment (called in daemon process)"""
        # Initialize API client (must be done in daemon process)
        self.api_client = APIClient()

        # Get Blender path
        self.blender_path = config.get_blender_path()
        if not self.blender_path:
            raise ValueError(
                "Blender path not configured. "
                "Set it with: nativeblend config set generation.blender_path /path/to/blender"
            )
        if not os.path.exists(self.blender_path):
            raise FileNotFoundError(f"Blender not found at: {self.blender_path}")

        self.logger.info(f"Using Blender at: {self.blender_path}")

    def process_task(self, task):
        """Process a single task"""
        task_id = task.get("id")
        self.logger.info(f"Processing task {task_id}")

        # Claim the task
        task_data = self.api_client.claim_task(task_id)
        if not task_data:
            self.logger.error(f"Failed to claim task {task_id}")
            self.stats.increment_failed()
            return

        code = task_data.get("code", "")
        artifact_path = task_data.get("artifact_path", "")
        self.stats.increment_in_progress()
        self.logger.info(f"Executing Blender script for task {task_id}")

        try:
            # Replace artifact_path with a local path instead of the API path
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
                self.logger.error(f"Error processing task {task_id}: {task_error}")
            else:
                self.logger.info(f"Task {task_id} completed successfully")

            self.logger.info(f"Artifact path: {result.get('artifact_path')}")

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
                self.logger.error(f"Failed to submit result for task {task_id}")
                self.stats.increment_failed()

            # Cleanup after upload
            if result.get("artifact_path") and os.path.exists(result["artifact_path"]):
                os.remove(result["artifact_path"])

        except Exception as e:
            self.logger.error(f"Error processing task {task_id}: {e}")
            self.api_client.completed(task_id, status="failed", error=str(e))
            self.stats.increment_failed()
        finally:
            # Save stats after each task
            self.stats.save_to_file()

    def run(self):
        """Main daemon loop - polls for tasks and executes them"""
        try:
            # Setup environment in daemon process
            self.setup_environment()

            self.stats.start()
            self.logger.info(
                f"Worker service started with {self.num_workers} worker(s), "
                f"poll interval: {self.poll_interval}s"
            )

            # Create thread pool for executing tasks
            self.executor = ThreadPoolExecutor(max_workers=self.num_workers)

            # Main polling loop
            while not self.got_sigterm():
                try:
                    # Get pending tasks
                    tasks = self.api_client.list_pending_tasks()

                    if tasks and len(tasks) > 0:
                        self.logger.info(f"Found {len(tasks)} pending task(s)")

                        # Submit tasks to executor
                        for task in tasks:
                            if self.got_sigterm():
                                break
                            future = self.executor.submit(self.process_task, task)
                            self.futures.add(future)

                        # Clean up completed futures
                        self.futures = {f for f in self.futures if not f.done()}

                    # Wait before polling again
                    time.sleep(self.poll_interval)

                    # Update status file periodically
                    self.stats.save_to_file()

                except Exception as e:
                    self.logger.error(f"Error in polling loop: {e}")
                    time.sleep(self.poll_interval)

        except Exception as e:
            self.logger.error(f"Fatal error in worker service: {e}")
            raise
        finally:
            # Cleanup
            self.logger.info("Worker service shutting down")
            if self.executor:
                self.logger.info("Waiting for tasks to complete...")
                self.executor.shutdown(wait=True)
            self.stats.save_to_file()
            self.logger.info("Worker service stopped")


def get_worker_service(num_workers: int = 1, poll_interval: int = 5) -> WorkerService:
    """Factory function to create a worker service instance"""
    return WorkerService(num_workers=num_workers, poll_interval=poll_interval)


def get_log_file_path() -> Path:
    """Get the path to the worker log file"""
    return LOG_FILE


def get_status_file_path() -> Path:
    """Get the path to the worker status file"""
    return STATUS_FILE


def load_status() -> Optional[dict]:
    """Load worker status from file"""
    try:
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None
