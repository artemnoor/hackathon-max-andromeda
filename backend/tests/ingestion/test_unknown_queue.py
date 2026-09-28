from andromeda.modules.disciplines.services.classifier import RuleBasedDisciplineClassifier
from andromeda.modules.disciplines.services.taxonomy import build_unknown_queue


def test_unknown_queue_groups_unresolved_names_and_keeps_program_scope() -> None:
    classifier = RuleBasedDisciplineClassifier()
    outcomes = (
        classifier.classify_with_outcome("Новая дисциплина"),
        classifier.classify_with_outcome("Новая дисциплина"),
        classifier.classify_with_outcome("Другой неизвестный предмет"),
    )

    queue = build_unknown_queue(
        outcomes,
        university_id="university:third",
        run_id="ingest:run-1",
        affected_programs={
            "новая дисциплина": ("program:third:01.03.01-01", "program:third:01.03.01-02"),
            "другой неизвестный предмет": ("program:third:01.03.01-02",),
        },
    )

    assert [item.normalized_name for item in queue] == ["другой неизвестный предмет", "новая дисциплина"]
    assert queue[1].source_count == 2
    assert queue[1].affected_programs == (
        "program:third:01.03.01-01",
        "program:third:01.03.01-02",
    )
    assert queue[0].review_state == "unreviewed"
