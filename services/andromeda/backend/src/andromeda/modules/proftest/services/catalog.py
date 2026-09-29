"""Application service for loading canonical catalog data through one port."""

from __future__ import annotations

import logging

from andromeda.modules.analytics.repository.ports import ProgramProjectionReader
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ..contracts.public import ProgramFingerprint
from ..domain.fingerprint_compat import fingerprint_from_projection
from ..repository.ports import BulkProftestCatalogReader, ProftestCatalogReader
from .fingerprint import FingerprintBuilder

logger = logging.getLogger("andromeda.proftest.catalog")


class ProftestCatalogService:
    def __init__(
        self,
        reader: ProftestCatalogReader,
        builder: FingerprintBuilder | None = None,
        projection_reader: ProgramProjectionReader | None = None,
    ) -> None:
        self._reader = reader
        self._builder = builder or FingerprintBuilder()
        self._projection_reader = projection_reader

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        if self._projection_reader is not None:
            projections = self._projection_reader.list()
            if projections:
                logger.info("catalog_projection_loaded fingerprint_count=%d source=program_analytics", len(projections))
                return tuple(fingerprint_from_projection(projection) for projection in projections)
            logger.info("program_projection_fallback reason=no_active_projection")
        if isinstance(self._reader, BulkProftestCatalogReader):
            try:
                snapshots = self._reader.list_catalog_snapshots()
            except Exception:
                logger.exception("[FIX:catalog-performance] bulk_snapshot_failed")
                raise
            logger.info("[FIX:catalog-performance] bulk_snapshot_loaded row_count=%d", len(snapshots))
            bulk_fingerprints: list[ProgramFingerprint] = []
            for snapshot in snapshots:
                if snapshot.curriculum is None:
                    logger.warning("catalog_curriculum_missing program_id=%s", _safe_id(snapshot.program.id))
                    continue
                disciplines = snapshot.disciplines
                for item in snapshot.curriculum.items:
                    discipline = disciplines.get(item.discipline_id)
                    if discipline is None:
                        logger.error(
                            "catalog_discipline_missing program_id=%s discipline_id=%s",
                            _safe_id(snapshot.program.id),
                            _safe_id(item.discipline_id),
                        )
                        raise ContractError(ErrorCode.CONTRACT_ERROR, "Curriculum item discipline is missing")
                bulk_fingerprints.append(self._builder.build(snapshot.program, snapshot.curriculum, disciplines))
            result = self._finish_fingerprints(len(snapshots), bulk_fingerprints)
            logger.info("[FIX:catalog-performance] bulk_snapshot_complete fingerprint_count=%d", len(result))
            return result

        programs = self._reader.list_programs()
        logger.info("catalog_refresh_start program_count=%d", len(programs))
        fingerprints: list[ProgramFingerprint] = []
        for program in programs:
            curriculum = self._reader.get_curriculum(program.id)
            if curriculum is None:
                logger.warning("catalog_curriculum_missing program_id=%s", _safe_id(program.id))
                continue
            disciplines = {}
            for item in curriculum.items:
                discipline = self._reader.get_discipline(item.discipline_id)
                if discipline is None:
                    logger.error("catalog_discipline_missing program_id=%s discipline_id=%s", _safe_id(program.id), _safe_id(item.discipline_id))
                    raise ContractError(ErrorCode.CONTRACT_ERROR, "Curriculum item discipline is missing")
                disciplines[item.discipline_id] = discipline
            fingerprints.append(self._builder.build(program, curriculum, disciplines))
        result = self._finish_fingerprints(len(programs), fingerprints)
        return result

    def _finish_fingerprints(self, program_count: int, fingerprints: list[ProgramFingerprint]) -> tuple[ProgramFingerprint, ...]:
        result = self._builder.add_distinctive_subjects(fingerprints)
        if len(result) < 2:
            logger.warning("catalog_distinctiveness_insufficient fingerprint_count=%d", len(result))
        logger.info("catalog_refresh_complete program_count=%d fingerprint_count=%d", program_count, len(result))
        return tuple(sorted(result, key=lambda fingerprint: fingerprint.program_code))


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["ProftestCatalogService"]
