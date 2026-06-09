"""
Shared pytest fixtures and session-level setup.

configure_logging(level="WARNING") is called once per session so that
tests don't produce log noise unless something actually goes wrong.
Individual tests can call configure_logging() again to override.
"""

import pytest

from core.logging import configure_logging


def pytest_configure(config: pytest.Config) -> None:
    configure_logging(level="WARNING", fmt="dev")
