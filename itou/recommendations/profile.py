import datetime
from dataclasses import dataclass, field

from django.contrib.gis.geos import Point


@dataclass(frozen=True, slots=True)
class DiagnosticConstraint:
    code: str
    impact: str | None = None


@dataclass(frozen=True, slots=True)
class BeneficiaryProfile:
    """
    Consolidated beneficiary profile built from France Travail APIs.

    Field names follow internal naming; mapping from FT API payloads
    is handled in `france_travail.py`.
    """

    france_travail_id: str

    # API Informations administratives usagers
    birthdate: datetime.date | None = None
    civility: str | None = None
    address_line: str | None = None
    city: str | None = None
    post_code: str | None = None
    code_insee: str | None = None
    coords: Point | None = None
    is_qpv_resident: bool | None = None

    # API Statut usager
    is_registered_at_france_travail: bool | None = None
    status_effective_date: datetime.date | None = None
    registration_duration_months: int | None = None

    # API Orientation usager
    education_level: str | None = None
    is_rsa_beneficiary: bool | None = None
    is_rqth_beneficiary: bool | None = None
    professional_situation: str | None = None

    # API Diagnostic usager
    has_declared_constraints: bool | None = None
    diagnostic_constraints: tuple[DiagnosticConstraint, ...] = field(default_factory=tuple)

    def age(self) -> int | None:
        # "age from birthdate in python" https://stackoverflow.com/a/9754466
        if self.birthdate is None:
            return None
        today = datetime.date.today()
        return (
            today.year - self.birthdate.year - ((today.month, today.day) < (self.birthdate.month, self.birthdate.day))
        )

    def months_since_registration(self) -> int | None:
        if self.status_effective_date is None:
            return self.registration_duration_months
        today = datetime.date.today()
        return (today.year - self.status_effective_date.year) * 12 + (today.month - self.status_effective_date.month)
