"""Smoke tests verifying the tsic package is importable via absolute imports."""

import tsic
from tsic import __version__


def test_package_importable() -> None:
    assert tsic.__name__ == "tsic"


def test_version_is_declared() -> None:
    assert __version__ == "0.1.0"
