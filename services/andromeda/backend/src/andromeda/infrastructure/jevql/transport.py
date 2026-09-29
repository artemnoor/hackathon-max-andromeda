"""Provider-neutral jevQL transport implementations."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from andromeda.modules.analytics.contracts.semantic_predicate import (
    SemanticPredicateRequest,
)

from .config import JevQLConfig


class JevQLTransportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JevQLTransport(Protocol):
    def available(self) -> bool: ...

    def evaluate(self, request: SemanticPredicateRequest) -> object: ...


class JevqlClient(Protocol):
    def judge(self, question: str, rows: list[Mapping[str, object]], *, kind: str, raw: bool) -> object: ...


class EmbeddedTransport:
    """Lazy official SDK adapter; the SDK is imported only on first use."""

    def __init__(self, client_factory: Callable[[], JevqlClient] | None = None) -> None:
        self._client_factory = client_factory or _official_embedded_client
        self._client: JevqlClient | None = None
        self._capability_error: str | None = None

    def available(self) -> bool:
        if self._client is not None:
            return True
        try:
            self._client = self._client_factory()
        except Exception as exc:
            self._capability_error = type(exc).__name__
            return False
        return True

    def evaluate(self, request: SemanticPredicateRequest) -> object:
        if not self.available() or self._client is None:
            raise JevQLTransportError("capability_unavailable", self._capability_error or "embedded SDK unavailable")
        return _judge(self._client, request)


class SharedServiceTransport:
    def __init__(
        self,
        config: JevQLConfig,
        *,
        requester: Callable[[SemanticPredicateRequest], object] | None = None,
        client_factory: Callable[[], JevqlClient] | None = None,
    ) -> None:
        if config.shared_endpoint is None:
            raise ValueError("shared jevQL endpoint is not configured")
        self._config = config
        self._requester = requester
        self._client_factory = client_factory or (
            lambda: _official_shared_client(
                self._config.shared_endpoint or "",
                self._config.shared_bearer_token,
            )
        )
        self._client: JevqlClient | None = None

    def available(self) -> bool:
        return self._requester is not None or self._config.shared_endpoint is not None

    def evaluate(self, request: SemanticPredicateRequest) -> object:
        if self._requester is not None:
            return self._requester(request)
        try:
            if self._client is None:
                self._client = self._client_factory()
            return _judge(self._client, request)
        except PermissionError as exc:
            raise JevQLTransportError("auth", "shared jevQL authorization failed") from exc
        except Exception as exc:
            raise JevQLTransportError("transport", "shared jevQL request failed") from exc


def _official_embedded_client() -> JevqlClient:
    try:
        import importlib

        module = importlib.import_module("jevql")
        factory = getattr(module, "Jevql", None)
        if not callable(factory):
            raise ImportError("jevQL SDK does not expose Jevql")
        return cast(JevqlClient, factory())
    except Exception as exc:
        raise RuntimeError("official jevQL Python SDK embedded engine is unavailable") from exc


def _official_shared_client(endpoint: str, token: str | None) -> JevqlClient:
    try:
        import importlib

        module = importlib.import_module("jevql")
        factory = getattr(module, "Jevql", None)
        if not callable(factory):
            raise ImportError("jevQL SDK does not expose Jevql")
        return cast(JevqlClient, factory(url=endpoint, token=token))
    except Exception as exc:
        raise RuntimeError("official jevQL Python SDK shared client is unavailable") from exc


def _judge(client: JevqlClient, request: SemanticPredicateRequest) -> dict[str, object]:
    rows: list[Mapping[str, object]] = [
        {"canonical_id": row.canonical_id, **dict(row.fields)}
        for row in request.rows
    ]
    # ``noul`` is the upstream jevQL boolean-judgement kind.  The pinned
    # SDK does not expose a ``bool`` kind; its JudgeAnswer is positional and
    # contains ``p``, ``passed`` and ``confidence`` instead of a row id.
    result = client.judge(request.predicate.question, rows, kind="noul", raw=True)
    answers = getattr(result, "answers", None)
    if not isinstance(answers, list):
        raise JevQLTransportError("internal", "upstream jevQL returned malformed judge result")
    if len(answers) > len(request.rows):
        raise JevQLTransportError("internal", "upstream jevQL returned answers for unknown rows")
    matches: dict[str, bool | None] = {}
    confidences: list[float] = []
    for index, row in enumerate(request.rows):
        if index >= len(answers):
            # The upstream model permits an absent answer.  Preserve that as
            # an unknown semantic result instead of dropping the input row.
            matches[row.canonical_id] = None
            continue
        answer = answers[index]
        probability = getattr(answer, "p", None)
        if probability is not None and (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(float(probability))
            or not 0 <= float(probability) <= 1
        ):
            raise JevQLTransportError("internal", "upstream jevQL returned a malformed probability")
        passed = getattr(answer, "passed", None)
        if passed is not None and not isinstance(passed, bool):
            raise JevQLTransportError("internal", "upstream jevQL returned a non-boolean answer")
        matches[row.canonical_id] = passed
        confidence = getattr(answer, "confidence", None)
        if confidence is not None:
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                raise JevQLTransportError("internal", "upstream jevQL returned a malformed confidence")
            confidences.append(float(confidence))
    return {
        "matches": matches,
        "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "provider": "jevql",
        "model": "upstream",
    }


__all__ = [
    "EmbeddedTransport",
    "JevQLTransport",
    "JevQLTransportError",
    "SharedServiceTransport",
]
