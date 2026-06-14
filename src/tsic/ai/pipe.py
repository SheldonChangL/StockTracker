"""Pipe formatted data to any AI CLI over a subprocess (Story 5.3; FR-21/FR-35).

tsic does not embed a specific LLM; instead it shapes data into text (Story 5.2)
and hands that text to whatever AI CLI the user points it at. This module is the
thin, dependency-free seam that does the handing-off so the user is never locked
to one model:

* :func:`run` launches the AI CLI as a subprocess, feeds the payload on its
  *stdin*, and returns its *stdout* verbatim — no parsing, no reshaping (AC-1).
* :func:`resolve_agent_command` decides which command to run: an explicit
  ``--agent "ollama run llama3"`` override wins over auto-detection (AC-2).
* :func:`read_payload` chooses the payload source: ``--stdin`` mode reads the
  payload straight from the process's stdin so tsic composes in a shell pipe
  (e.g. ``tsic query ... | tsic analyze --stdin``) (AC-3).

The subprocess call is injected rather than hard-wired, so the piping behaviour
can be exercised against a fake echo process without spawning anything real
(AC-1), mirroring the injectable-probe pattern in :mod:`tsic.ai.detector`.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Callable
from typing import IO

from tsic.ai.detector import Probe, detect

#: Runner signature: given the parsed argv and the payload to feed on stdin,
#: return the subprocess's stdout. Injectable so tests use a fake echo (AC-1).
Runner = Callable[[list[str], str], str]


def _subprocess_runner(argv: list[str], payload: str) -> str:
    """Default runner: spawn ``argv``, feed ``payload`` on stdin, return stdout."""
    completed = subprocess.run(
        argv,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout


def run(agent_cmd: str, payload: str, *, runner: Runner = _subprocess_runner) -> str:
    """Pipe ``payload`` to the ``agent_cmd`` subprocess and return its stdout (AC-1).

    The command string is split with :func:`shlex.split`, so a multi-word
    command such as ``"ollama run llama3"`` becomes the argv ``["ollama",
    "run", "llama3"]``. The payload is written to the child's stdin and the
    child's stdout is returned unchanged (FR-21).

    Args:
        agent_cmd: The AI CLI command to execute, e.g. ``"claude"`` or
            ``"ollama run llama3"``.
        payload: The formatted text fed to the child process on stdin.
        runner: Callable performing the actual subprocess execution. Defaults
            to a real :func:`subprocess.run`; tests inject a fake that echoes
            stdin so no process is spawned (AC-1).

    Returns:
        The child process's stdout, returned verbatim.

    Raises:
        ValueError: If ``agent_cmd`` is empty or only whitespace, since there is
            no command to run.
    """
    argv = shlex.split(agent_cmd)
    if not argv:
        raise ValueError("agent command is empty; nothing to run")
    return runner(argv, payload)


def resolve_agent_command(
    override: str | None = None, *, probe: Probe | None = None
) -> str | None:
    """Return the AI CLI command to run, preferring an explicit override (AC-2).

    When ``--agent`` is supplied (``override`` non-empty) that exact command is
    used and auto-detection is skipped entirely, so the user can target any CLI
    (e.g. ``"ollama run llama3"``) regardless of what is installed (AC-2). When
    no override is given the installed CLI is detected via
    :func:`tsic.ai.detector.detect`, which returns the bare executable name or
    ``None`` when none is available.

    Args:
        override: The ``--agent`` value, or ``None``/empty to auto-detect.
        probe: Optional PATH probe forwarded to :func:`detect` for auto-detection;
            ignored when ``override`` is given. Injectable for tests.

    Returns:
        The command string to run, or ``None`` when no override is given and no
        AI CLI is detected.
    """
    if override is not None and override.strip():
        return override
    if probe is not None:
        return detect(probe)
    return detect()


def read_payload(
    use_stdin: bool, payload: str | None = None, *, stream: IO[str] | None = None
) -> str:
    """Return the payload to pipe, reading stdin in ``--stdin`` mode (AC-3).

    In ``--stdin`` mode the payload is read directly from the process's stdin,
    so tsic slots into a shell pipe (``tsic query ... | tsic analyze --stdin``)
    and uses the upstream output as-is (AC-3). Otherwise the caller-supplied
    ``payload`` (e.g. the Markdown produced from the local cache) is used.

    Args:
        use_stdin: Whether ``--stdin`` was requested.
        payload: The pre-built payload to use when not in stdin mode.
        stream: The stream read in stdin mode; defaults to :data:`sys.stdin`.
            Injectable so tests feed a fake stdin (AC-3).

    Returns:
        The payload string to pipe to the AI CLI.

    Raises:
        ValueError: If ``use_stdin`` is false and no ``payload`` was supplied,
            since there would be nothing to pipe.
    """
    if use_stdin:
        source = stream if stream is not None else sys.stdin
        return source.read()
    if payload is None:
        raise ValueError("no payload supplied and --stdin not set")
    return payload
