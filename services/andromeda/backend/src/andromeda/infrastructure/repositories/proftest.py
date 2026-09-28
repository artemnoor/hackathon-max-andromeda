"""Infrastructure adapter composing existing canonical module readers."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from threading import RLock
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.disciplines.repository.ports import DisciplineReader
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.modules.proftest.repository.ports import ProftestCatalogReader, ProftestCatalogSnapshot
from andromeda.shared.contracts.ids import DisciplineId, ProgramId

from ..database.models import IngestRunModel


logger = logging.getLogger("andromeda.infrastructure.repositories.proftest")


@runtime_checkable
class _BatchCurriculumReader(Protocol):
    def list_for_programs(self, program_ids: tuple[ProgramId, ...]) -> dict[ProgramId, Curriculum]: ...


@runtime_checkable
class _BatchDisciplineReader(Protocol):
    def get_many(self, discipline_ids: tuple[DisciplineId, ...]) -> Mapping[DisciplineId, Discipline]: ...


class _CatalogSnapshotCacheEntry:
    def __init__(self, revision: tuple[str | None, str | None], snapshots: tuple[ProftestCatalogSnapshot, ...]) -> None:
        self.revision = revision
        self.snapshots = snapshots


_CATALOG_SNAPSHOT_CACHE: dict[Engine, _CatalogSnapshotCacheEntry] = {}
_CATALOG_SNAPSHOT_CACHE_LOCK = RLock()


class SqlAlchemyProftestCatalogRepository(ProftestCatalogReader):
    """Composition adapter; SQLAlchemy stays hidden by the delegated readers."""

    def __init__(
        self,
        programs: ProgramReader,
        curricula: CurriculumReader,
        disciplines: DisciplineReader,
        session: Session | None = None,
    ) -> None:
        self._programs = programs
        self._curricula = curricula
        self._disciplines = disciplines
        self._session = session

    def list_programs(self) -> tuple[Program, ...]:
        return self._programs.list()

    def get_curriculum(self, program_id: ProgramId) -> Curriculum | None:
        return self._curricula.get_for_program(program_id)

    def get_discipline(self, discipline_id: DisciplineId) -> Discipline | None:
        return self._disciplines.get(discipline_id)

    def list_catalog_snapshots(self) -> tuple[ProftestCatalogSnapshot, ...]:
        """Build the recommendation input with bounded SQL reads."""

        if self._session is not None:
            bind = self._session.get_bind()
            if isinstance(bind, Engine):
                revision = self._catalog_revision()
                with _CATALOG_SNAPSHOT_CACHE_LOCK:
                    cached = _CATALOG_SNAPSHOT_CACHE.get(bind)
                    if cached is not None and cached.revision == revision:
                        logger.debug("[FIX:catalog-performance] bulk_snapshot_cache_hit")
                        return cached.snapshots
                    snapshots = self._build_catalog_snapshots()
                    _CATALOG_SNAPSHOT_CACHE[bind] = _CatalogSnapshotCacheEntry(revision, snapshots)
                    logger.info(
                        "[FIX:catalog-performance] bulk_snapshot_cache_refresh revision=%s row_count=%d",
                        revision[1] or "none",
                        len(snapshots),
                    )
                    return snapshots
        return self._build_catalog_snapshots()

    def _catalog_revision(self) -> tuple[str | None, str | None]:
        if self._session is None:
            return (None, None)
        row = self._session.execute(
            select(IngestRunModel.id, IngestRunModel.finished_at)
            .where(IngestRunModel.status == "completed")
            .order_by(IngestRunModel.finished_at.desc(), IngestRunModel.id.desc())
            .limit(1)
        ).first()
        if row is None:
            return (None, None)
        return (row[0], row[1].isoformat() if row[1] is not None else None)

    def _build_catalog_snapshots(self) -> tuple[ProftestCatalogSnapshot, ...]:
        programs = self._programs.list()
        program_ids = tuple(program.id for program in programs)
        if not isinstance(self._curricula, _BatchCurriculumReader):
            return self._fallback_snapshots(programs)
        curricula = self._curricula.list_for_programs(program_ids)
        discipline_ids = tuple(
            dict.fromkeys(
                item.discipline_id
                for curriculum in curricula.values()
                for item in curriculum.items
            )
        )
        if isinstance(self._disciplines, _BatchDisciplineReader):
            disciplines = self._disciplines.get_many(discipline_ids)
        else:
            fallback_disciplines: dict[DisciplineId, Discipline] = {}
            for discipline_id in discipline_ids:
                discipline = self._disciplines.get(discipline_id)
                if discipline is not None:
                    fallback_disciplines[discipline_id] = discipline
            disciplines = fallback_disciplines
        return tuple(
            ProftestCatalogSnapshot(program, curricula.get(program.id), disciplines)
            for program in programs
        )

    def _fallback_snapshots(self, programs: tuple[Program, ...]) -> tuple[ProftestCatalogSnapshot, ...]:
        snapshots: list[ProftestCatalogSnapshot] = []
        for program in programs:
            curriculum = self._curricula.get_for_program(program.id)
            disciplines: dict[DisciplineId, Discipline] = {}
            if curriculum is not None:
                for item in curriculum.items:
                    discipline = self._disciplines.get(item.discipline_id)
                    if discipline is not None:
                        disciplines[item.discipline_id] = discipline
            snapshots.append(ProftestCatalogSnapshot(program, curriculum, disciplines))
        return tuple(snapshots)


__all__ = ["SqlAlchemyProftestCatalogRepository"]
