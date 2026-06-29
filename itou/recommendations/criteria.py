import enum
from dataclasses import dataclass, field

from django.contrib.gis.geos import Point


class StructuredSolutionKind(enum.StrEnum):
    PLIE = "plie"
    EPIDE = "epide"
    E2C = "ecoles-de-la-deuxieme-chance"
    APPRENTIS_DAUTEUIL_ACCOMPAGNEMENT_INTENSIF = "apprentis-dauteuil-accompagnement-intensif"
    APPRENTIS_DAUTEUIL_SKOLA = "apprentis-dauteuil-skola"
    APPRENTIS_DAUTEUIL_BOOST_INSERTION = "apprentis-dauteuil-boost-insertion"
    APPRENTIS_DAUTEUIL_POTENTIELLES = "apprentis-dauteuil-potentielles"
    SIAE = "siae"
    EA = "ea"
    GEIQ = "geiq"


class CriterionStatus(enum.StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CriterionEvaluation:
    code: str
    label: str
    status: CriterionStatus
    is_mandatory: bool = True


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    kind: StructuredSolutionKind
    is_eligible: bool
    criteria: tuple[CriterionEvaluation, ...] = field(default_factory=tuple)

    @property
    def matched_criteria_count(self) -> int:
        return sum(criterion.status is CriterionStatus.MET for criterion in self.criteria)

    @property
    def unknown_criteria_count(self) -> int:
        return sum(criterion.status is CriterionStatus.UNKNOWN for criterion in self.criteria)

    def reasons(self) -> list[str]:
        return [criterion.label for criterion in self.criteria if criterion.status is CriterionStatus.MET]


@dataclass(frozen=True, slots=True)
class StructuredSolutionCandidate:
    """
    Lightweight value object consumed by the eligibility rules.

    In production, built from an ``insertion.models.Service`` instance via
    ``from_service()``.  Kept as a thin dataclass so the rules stay decoupled
    from the ORM and tests can run without a database.
    """

    kind: StructuredSolutionKind
    coordinates: Point | None = None
    eligibility_zones: tuple[str, ...] = field(default_factory=tuple)
