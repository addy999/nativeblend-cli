"""Worker manager for executing Blender tasks from NativeBlend API"""

import os
import sys
import time
import json
import signal
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import daemon
from daemon.pidfile import TimeoutPIDLockFile
import psutil
import threading

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
PID_FILE = WORKER_DIR / "worker.pid"


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
        acquired = self.lock.acquire(timeout=2.0)
        if not acquired:
            return
        try:
            self.tasks_completed += 1
            self.tasks_in_progress -= 1
        finally:
            self.lock.release()

    def increment_failed(self):
        acquired = self.lock.acquire(timeout=2.0)
        if not acquired:
            return
        try:
            self.tasks_failed += 1
            self.tasks_in_progress -= 1
        finally:
            self.lock.release()

    def increment_in_progress(self):
        acquired = self.lock.acquire(timeout=2.0)
        if not acquired:
            return
        try:
            self.tasks_in_progress += 1
        finally:
            self.lock.release()

    def get_stats(self):
        acquired = self.lock.acquire(timeout=2.0)
        if not acquired:
            return {}
        try:
            result = {
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
            return result
        finally:
            self.lock.release()

    def save_to_file(self):
        """Save stats to file for status command"""

        caller = threading.current_thread().name
        try:
            # Use timeout to detect deadlocks
            acquired = self.lock.acquire(timeout=2.0)
            if not acquired:
                # Failed to acquire lock - potential deadlock
                return
            try:
                stats = self.get_stats()
                with open(STATUS_FILE, "w") as f:
                    json.dump(stats, f, indent=2)
            finally:
                self.lock.release()
        except Exception:
            pass  # Ignore errors writing status file


class WorkerDaemon:
    """Background daemon that executes Blender tasks"""

    blender_path: str

    def __init__(self, num_workers: int = 1, poll_interval: int = 5):
        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self.executor: Optional[ThreadPoolExecutor] = None
        self.api_client = APIClient()
        self.stats = WorkerStats()
        self.futures: set[Future] = set()
        self.running = False
        self.logger = logging.getLogger("nativeblend-worker")

    def setup_logging(self):
        """Setup logging - must be called after daemonization"""
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        # Add rotating file handler (10MB max, keep 3 backups)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def setup_environment(self):
        """Setup worker environment"""
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
        generation: str = task_data.get("generation", "")
        assert generation, "Generation ID is required in task data"

        self.stats.increment_in_progress()
        self.logger.info(f"Executing Blender script for task {task_id}")

        try:
            # Replace artifact_path with a local path
            if artifact_path:
                filename = os.path.basename(artifact_path)
                new_artifact_path = os.path.abspath(
                    os.path.join(config.get("output.default_dir"), generation, filename)
                )  # need abs path here because `worker` runs in a different working directory after daemonization

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

            # Determine status
            task_status = "failed" if result.get("error") else "completed"
            task_output = result.get("output", "")
            task_error = result.get("error")

            if task_error:
                self.logger.error(f"Error processing task {task_id}: {task_error}")
            else:
                self.logger.info(f"Task {task_id} completed successfully")

            # Submit the result with artifact
            artifact_file = None
            try:
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
                    self.logger.info(
                        f"Successfully submitted result for task {task_id}"
                    )
                else:
                    self.logger.error(f"Failed to submit result for task {task_id}")
                    self.stats.increment_failed()

            finally:
                # Always close the file handle
                if artifact_file:
                    artifact_file.close()
                    self.logger.debug(f"Closed artifact file for task {task_id}")

                # Cleanup artifact file
                if result.get("artifact_path") and os.path.exists(
                    result["artifact_path"]
                ):
                    is_image = (
                        result["artifact_path"]
                        .lower()
                        .endswith((".png", ".jpg", ".jpeg"))
                        and "behind" not in result["artifact_path"].lower()
                    )  # crude check for renders vs model files
                    is_blend_file = result["artifact_path"].lower().endswith(".blend")

                    # Remove images unless we're saving them
                    if is_blend_file or (
                        is_image and config.get("output.save_renders")
                    ):
                        self.logger.info(
                            f"Saving file for task {task_id} at {result['artifact_path']}"
                        )
                        return

                    # Else, remove artifact
                    try:
                        os.remove(result["artifact_path"])
                    except Exception as cleanup_error:
                        self.logger.warning(
                            f"Failed to delete image for task {task_id}: {cleanup_error}"
                        )

        except Exception as e:
            self.logger.error(f"Error processing task {task_id}: {e}", exc_info=True)
            try:
                self.api_client.completed(task_id, status="failed", error=str(e))
                self.stats.increment_failed()
            except Exception as submit_error:
                self.logger.error(
                    f"Failed to submit error status for task {task_id}: {submit_error}",
                    exc_info=True,
                )
                self.stats.increment_failed()
        finally:
            self.stats.save_to_file()
            self.logger.debug(f"Finished processing task {task_id}")

    def handle_sigterm(self, signum, frame):
        """Handle SIGTERM signal"""
        self.logger.info("Received SIGTERM, shutting down...")
        self.running = False

    def run(self):
        """Main daemon loop"""
        try:
            # Setup logging first (after daemonization)
            self.setup_logging()

            # Setup signal handler
            signal.signal(signal.SIGTERM, self.handle_sigterm)

            # Setup environment
            self.setup_environment()

            self.stats.start()
            self.running = True
            self.logger.info(
                f"Worker daemon started with {self.num_workers} worker(s), "
                f"poll interval: {self.poll_interval}s"
            )

            # Create thread pool
            self.executor = ThreadPoolExecutor(max_workers=self.num_workers)

            # Main polling loop
            poll_count = 0
            self.logger.info("Entering main polling loop")
            while self.running:
                try:
                    poll_count += 1
                    self.logger.info(f"=== Starting poll iteration #{poll_count} ===")

                    # Get pending tasks
                    self.logger.debug("Polling for pending tasks...")
                    tasks = self.api_client.list_pending_tasks()

                    if tasks and len(tasks) > 0:
                        self.logger.info(f"Found {len(tasks)} pending task(s)")

                        # Submit tasks to executor
                        for task in tasks:
                            if not self.running:
                                self.logger.warning("Stopping - self.running is False")
                                break
                            future = self.executor.submit(self.process_task, task)
                            self.futures.add(future)

                        # Clean up completed futures
                        # completed_count = len([f for f in self.futures if f.done()])
                        self.futures = {f for f in self.futures if not f.done()}

                    else:
                        self.logger.debug("No pending tasks found")

                    # Wait before polling again
                    self.logger.info(f"About to sleep for {self.poll_interval}s")
                    try:
                        time.sleep(self.poll_interval)
                        self.logger.info(f"Woke up from sleep normally")
                    except InterruptedError as ie:
                        self.logger.warning(f"Sleep interrupted: {ie}")
                    except Exception as sleep_error:
                        self.logger.error(
                            f"Unexpected error during sleep: {sleep_error}",
                            exc_info=True,
                        )

                    self.stats.save_to_file()
                    self.logger.info(f"=== Completed poll iteration #{poll_count} ===")

                except Exception as e:
                    self.logger.error(f"Error in polling loop: {e}", exc_info=True)
                    self.logger.info(f"Sleeping {self.poll_interval}s after exception")
                    time.sleep(self.poll_interval)
                    self.logger.info("Woke up from exception sleep")

        except Exception as e:
            self.logger.error(f"Fatal error in worker daemon: {e}")
            raise
        finally:
            # Cleanup
            self.logger.info("Worker daemon shutting down")
            if self.executor:
                self.logger.info("Waiting for tasks to complete...")
                self.executor.shutdown(wait=True)
            self.stats.save_to_file()
            self.logger.info("Worker daemon stopped")


def start_worker(num_workers: int = 1, poll_interval: int = 5):
    """Start worker daemon in background"""

    if is_running():
        raise RuntimeError("Worker is already running")

    # Create daemon context
    pidfile = TimeoutPIDLockFile(PID_FILE, timeout=3)

    context = daemon.DaemonContext(
        pidfile=pidfile,
        working_directory=str(WORKER_DIR),
        files_preserve=[],  # set after creating worker
        detach_process=True,
    )

    # create worker inside the context to avoid FD issues
    with context:
        worker = WorkerDaemon(num_workers=num_workers, poll_interval=poll_interval)
        worker.run()


def stop_worker():
    """Stop running worker daemon"""
    if not is_running():
        raise RuntimeError("Worker is not running")

    pid = get_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            # wait for process to stop, up to 10 seconds
            for _ in range(50):
                if not is_running():
                    break
                time.sleep(0.2)
        except ProcessLookupError:
            pass  # already stopped
        finally:
            if PID_FILE.exists():
                PID_FILE.unlink()


def is_running() -> bool:
    """Check if worker daemon is running"""
    if not PID_FILE.exists():
        return False

    try:
        pid = get_pid()
        if pid is None:
            return False

        try:
            process = psutil.Process(pid)
            return process.is_running() and "python" in process.name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    except Exception:
        return False


def get_pid() -> Optional[int]:
    """Get worker daemon PID"""
    if not PID_FILE.exists():
        return None

    try:
        with open(PID_FILE, "r") as f:
            content = f.read().strip()
            return int(content) if content else None
    except Exception:
        return None


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
