"""Detect which AI CLI is installed on PATH (Story 5.1; FR-20/FR-34).

tsic can drive an external AI CLI, but rather than make the user name it on
every invocation it detects an installed one automatically. The detection is a
fixed preference order — ``claude`` first, then ``openai``, then ``llm`` — so
when several are present the most preferred wins (AC-1) and a sole survivor is
still found (AC-2). When none is installed the detector returns ``None`` so the
command layer can map that to the documented "no AI CLI" exit code 3 (AC-3).

PATH probing is injected rather than hard-wired to :func:`shutil.which`, so the
detector can be exercised deterministically without depending on what is really
installed on the test machine (AC-4).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable

#: AI CLIs in descending preference order; the first available one wins (AC-1).
CLI_PRIORITY: tuple[str, ...] = ("claude", "openai", "llm")

#: Probe signature: given an executable name, report whether it is on PATH.
#: Injectable so tests do not depend on real installations (AC-4).
Probe = Callable[[str], bool]


def _which_probe(name: str) -> bool:
    """Default probe: report whether ``name`` resolves on PATH via ``which``."""
    return shutil.which(name) is not None


def detect(probe: Probe = _which_probe) -> str | None:
    """Return the most preferred installed AI CLI name, or ``None``.

    The names in :data:`CLI_PRIORITY` are probed in order and the first one the
    ``probe`` reports as available is returned, so ``claude`` is preferred over
    ``openai`` over ``llm`` (AC-1/AC-2). If none is available the result is
    ``None`` (AC-3).

    Args:
        probe: Callable deciding whether a given executable name is available.
            Defaults to a :func:`shutil.which` lookup against the real PATH;
            tests inject a fake to avoid depending on installed binaries (AC-4).

    Returns:
        The detected CLI name (``"claude"`` / ``"openai"`` / ``"llm"``), or
        ``None`` when none of them is available.
    """
    for name in CLI_PRIORITY:
        if probe(name):
            return name
    return None
