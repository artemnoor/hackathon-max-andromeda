from __future__ import annotations

from pathlib import Path

from andromeda.infrastructure.jev.align import JevAlignConfig, JevAlignSession, JevAlignStoryInput


class _Backend:
    pass


def test_jev_align_session_is_backed_by_upstream_climb_session(tmp_path: Path) -> None:
    session = JevAlignSession.create(
        (
            JevAlignStoryInput("story-1", {"content": "Математический анализ"}),
            JevAlignStoryInput("story-2", {"content": "Программирование"}),
        ),
        config=JevAlignConfig(
            run_directory=tmp_path / "run",
            task_instructions="Classify semantic features in curriculum disciplines.",
            feature_criteria={
                "mathematics": ("The discipline is mathematical.", "It is not mathematical."),
            },
            batch_size=1,
        ),
        backend=_Backend(),
    )

    assert session.upstream_session.__class__.__name__ == "ClimbSession"
    assert (tmp_path / "run" / "state.json").exists()
    assert (tmp_path / "run" / "source.jsonl").exists()


def test_jev_align_session_rejects_reusing_run_directory(tmp_path: Path) -> None:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    try:
        JevAlignSession.create(
            (JevAlignStoryInput("story-1", {"content": "x"}),),
            config=JevAlignConfig(
                run_directory=run_directory,
                task_instructions="Classify.",
                feature_criteria={"mathematics": ("yes", "no")},
            ),
            backend=_Backend(),
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected existing run directory to fail closed")
