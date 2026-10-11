"""ModelAnvil CLI package.

Provides the programmatic API client and command-line interface for the
API-only developer journey (TECH-004) and hybrid worker operations (TECH-029).
"""

from modelanvil.cli.client import ModelAnvilClient
from modelanvil.cli.main import main

__all__ = ["ModelAnvilClient", "main"]
