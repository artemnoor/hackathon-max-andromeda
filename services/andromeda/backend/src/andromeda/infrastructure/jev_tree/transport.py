"""Transport-only subprocess boundary for the optional Node package."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Protocol

from .config import JevTreeConfig


class JevTreeTransport(Protocol):
    def select(self, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]: ...


class NodeJevTreeTransport:
    """Invoke the pinned bridge with JSON over stdin/stdout.

    The application never imports Node or the npm package.  Only a minimal
    provider-key environment allowlist crosses the process boundary.
    """

    def __init__(self, config: JevTreeConfig) -> None:
        self._config = config

    def select(self, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        if not self._config.enabled:
            raise RuntimeError("jev-tree is disabled")
        command = (self._config.node_binary, str(self._config.bridge_path))
        environment = {"PATH": os.environ.get("PATH", "")}
        environment.update(
            {
                key: value
                for key in ("AI_GATEWAY_API_KEY", "TYPESAFE_API_KEY")
                if (value := os.environ.get(key))
            }
        )
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                shell=False,
                cwd=self._config.working_directory,
                env=environment,
                timeout=min(timeout_seconds, self._config.timeout_seconds),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("jev-tree bridge unavailable") from exc
        if completed.returncode != 0:
            raise RuntimeError("jev-tree bridge failed")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("jev-tree bridge returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("jev-tree bridge returned a non-object")
        return value


__all__ = ["JevTreeTransport", "NodeJevTreeTransport"]
