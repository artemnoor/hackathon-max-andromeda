from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, HttpUrl

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear


class BmstuAdmissionDocumentKind(StrEnum):
    RULES = "rules"
    APPENDIX_5 = "appendix_5"
    APPENDIX_5_1 = "appendix_5_1"
    APPENDIX_5_2 = "appendix_5_2"
    APPENDIX_5_3 = "appendix_5_3"
    APPENDIX_5_4 = "appendix_5_4"
    APPENDIX_5_5 = "appendix_5_5"
    APPENDIX_6 = "appendix_6"
    APPENDIX_7 = "appendix_7"
    APPENDIX_8_1 = "appendix_8_1"
    APPENDIX_8_3 = "appendix_8_3"
    OTHER = "other"


class BmstuAdmissionDocumentSpec(ContractModel):
    """One official document discovered from the BMSTU admission index."""

    index_id: int = Field(strict=True, ge=1)
    title: str = Field(min_length=1, max_length=512)
    url: HttpUrl
    admission_year: EducationYear
    kind: BmstuAdmissionDocumentKind
    appendix_number: str | None = Field(default=None, max_length=32)
    selected: bool = True


class BmstuAdmissionSourceManifest(ContractModel):
    """Validated document selection, including non-selected index entries."""

    index_url: HttpUrl
    admission_year: EducationYear
    discovered: tuple[BmstuAdmissionDocumentSpec, ...] = ()
    selected: tuple[BmstuAdmissionDocumentSpec, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def selected_kinds(self) -> frozenset[BmstuAdmissionDocumentKind]:
        return frozenset(document.kind for document in self.selected)

    @property
    def required_kinds(self) -> frozenset[BmstuAdmissionDocumentKind]:
        return frozenset(
            {
                BmstuAdmissionDocumentKind.RULES,
                BmstuAdmissionDocumentKind.APPENDIX_5,
                BmstuAdmissionDocumentKind.APPENDIX_5_1,
                BmstuAdmissionDocumentKind.APPENDIX_5_2,
                BmstuAdmissionDocumentKind.APPENDIX_5_3,
                BmstuAdmissionDocumentKind.APPENDIX_5_4,
                BmstuAdmissionDocumentKind.APPENDIX_5_5,
                BmstuAdmissionDocumentKind.APPENDIX_6,
            }
        )

    @property
    def missing_required_kinds(self) -> frozenset[BmstuAdmissionDocumentKind]:
        return self.required_kinds - self.selected_kinds


@dataclass(frozen=True, slots=True)
class BmstuAdmissionDocumentIndexItem:
    index_id: int
    title: str
    url: str


__all__ = [
    "BmstuAdmissionDocumentIndexItem",
    "BmstuAdmissionDocumentKind",
    "BmstuAdmissionDocumentSpec",
    "BmstuAdmissionSourceManifest",
]
