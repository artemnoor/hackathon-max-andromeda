from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base, create_engine_for_url
from scripts.report_knowledge_provenance import collect_report


def test_legacy_provenance_report_is_read_only_and_keeps_empty_state_explicit() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        statements: list[str] = []

        def record_statement(_connection, _cursor, statement, *_args) -> None:
            statements.append(statement.lstrip().split(None, 1)[0].upper())

        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            with Session(engine) as session:
                report = collect_report(session)
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)

        assert report["mode"] == "read_only"
        assert report["writesPerformed"] is False
        assert report["approvalInferred"] is False
        benefit_rows = report["benefitOwnerRows"]
        assert isinstance(benefit_rows, dict)
        assert len(benefit_rows) == 5
        assert all(item["records"] == 0 for item in benefit_rows.values())
        assert set(statements) == {"SELECT"}
    finally:
        engine.dispose()
