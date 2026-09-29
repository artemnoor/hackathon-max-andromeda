"""Configuration for the isolated Node jev-tree bridge."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel


class JevTreeConfig(ContractModel):
    enabled: bool = False
    node_binary: str = Field(default="node", min_length=1, max_length=128)
    bridge_path: Path
    working_directory: Path | None = None
    timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    max_fanout: int = Field(default=32, strict=True, ge=2, le=255)
    max_depth: int = Field(default=16, strict=True, ge=1, le=32)
    max_calls: int = Field(default=64, strict=True, ge=1, le=256)


__all__ = ["JevTreeConfig"]
