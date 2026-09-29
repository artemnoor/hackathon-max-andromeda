from __future__ import annotations

from fastapi import Request

from andromeda.composition import AndromedaContainer


def get_composition_root(request: Request) -> AndromedaContainer:
    """Return the application-owned composition graph.

    App construction installs this object before any route can be served. A
    missing root is a wiring error and must fail explicitly instead of
    rebuilding a second graph from environment defaults.
    """

    container = getattr(request.app.state, "container", None)
    if not isinstance(container, AndromedaContainer):
        raise RuntimeError("Andromeda composition root is not configured")
    return container


__all__ = ["get_composition_root"]
