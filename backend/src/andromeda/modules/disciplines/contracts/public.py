"""Public discipline contracts; source name remains on curriculum items."""

from .classification import ClassificationOutcome, TAXONOMY_VERSION
from ..domain.areas import DisciplineAreaCode, DisciplineAreaDefinition, DisciplineAreaSummary, DisciplineAreaWeight, area_catalog, area_definition, area_position
from ..domain.entities import Discipline

__all__ = [
    "ClassificationOutcome",
    "Discipline",
    "DisciplineAreaCode",
    "DisciplineAreaDefinition",
    "DisciplineAreaSummary",
    "DisciplineAreaWeight",
    "TAXONOMY_VERSION",
    "area_catalog",
    "area_definition",
    "area_position",
]
