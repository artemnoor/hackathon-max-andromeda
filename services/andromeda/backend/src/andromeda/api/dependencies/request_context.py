from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.session import session_factory


def get_session(request: Request) -> Iterator[Session]:
    factory = session_factory(request.app.state.engine)
    with factory() as session:
        yield session
