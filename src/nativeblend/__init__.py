"""NativeBlend CLI"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("nativeblend")
except PackageNotFoundError:
    # Package is not installed, use a fallback version
    __version__ = "dev"

__all__ = ["__version__"]
