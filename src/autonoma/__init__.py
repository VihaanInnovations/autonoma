"""
Autonoma - Deterministic code security scanner.
"""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("autonoma-cli")
except PackageNotFoundError:
    __version__ = "0.1.9"
