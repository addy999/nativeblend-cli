import json
import os
from pathlib import Path
from typing import Optional, Any
import keyring
import platform

# Constants
CONFIG_DIR = Path.home() / ".config" / "nativeblend"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEYRING_SERVICE = "nativeblend-cli"
KEYRING_USERNAME = "api-key"
DEFAULT_API_ENDPOINT = "https://blender-ai.fly.dev"


def _get_default_blender_path() -> str:
    """Get default Blender path based on operating system"""
    system = platform.system()
    if system == "Darwin":  # macOS
        return "/Applications/Blender.app/Contents/MacOS/Blender"
    elif system == "Windows":
        return "C:\\Program Files\\Blender Foundation\\Blender\\blender.exe"
    else:  # Linux and other Unix-like systems
        return "/usr/bin/blender"


DEFAULT_BLENDER_PATH = _get_default_blender_path()


class Config:
    """Manages CLI configuration and API key storage"""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_file = CONFIG_FILE
        self._data = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from file"""
        if not self.config_file.exists():
            return self._get_default_config()

        try:
            with open(self.config_file, "r") as f:
                loaded_config = json.load(f)
        except (json.JSONDecodeError, IOError):
            return self._get_default_config()

        # Merge loaded config with defaults to ensure all keys are present
        merged_config = self._merge_configs(self._get_default_config(), loaded_config)

        # If the config was missing keys, save the updated config
        if merged_config != loaded_config:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w") as f:
                json.dump(merged_config, f, indent=2)

        return merged_config

    def _get_default_config(self) -> dict:
        """Get default configuration"""
        return {
            "api": {
                "endpoint": DEFAULT_API_ENDPOINT,
                "timeout": 300,
            },
            "output": {
                "default_dir": os.path.abspath("./outputs"),
                "save_renders": True,
            },
            "generation": {
                "default_mode": "standard",
                "blender_path": DEFAULT_BLENDER_PATH,
            },
        }

    def _merge_configs(self, defaults: dict, loaded: dict) -> dict:
        """Deep merge loaded config with defaults, preserving loaded values"""
        result = defaults.copy()

        for key, value in loaded.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dicts
                result[key] = self._merge_configs(result[key], value)
            else:
                # Use loaded value if it exists
                result[key] = value

        return result

    def save(self) -> None:
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation (e.g., 'api.endpoint')"""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    # TODO: If setting output dir, assert that it is an abs path and create it if it doesn't exist.
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value using dot notation (e.g., 'api.endpoint')"""
        keys = key.split(".")
        data = self._data

        # Navigate to the nested dict
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]

        # Set the value
        data[keys[-1]] = value
        self.save()

    def get_api_key(self) -> Optional[str]:
        """Get API key from system keychain"""
        try:
            return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            return None

    def set_api_key(self, api_key: str) -> None:
        """Store API key in system keychain"""
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)

    def delete_api_key(self) -> None:
        """Delete API key from system keychain"""
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass  # Key doesn't exist

    def get_api_endpoint(self) -> str:
        """Get API endpoint URL"""
        return self.get("api.endpoint", DEFAULT_API_ENDPOINT)

    def get_timeout(self) -> int:
        """Get API timeout in seconds"""
        return self.get("api.timeout", 300)

    def get_blender_path(self) -> str:
        """Get Blender executable path"""
        return self.get("generation.blender_path", DEFAULT_BLENDER_PATH)

    def initialize(self) -> None:
        """Initialize configuration directory and file with defaults"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self._data = self._get_default_config()
            self.save()


# Global config instance
config = Config()
