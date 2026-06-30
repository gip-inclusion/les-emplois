import enum
from abc import ABC, abstractmethod

from itou.geo.utils import distance_in_km
from itou.recommendations.criteria import (
    CriterionEvaluation,
    CriterionStatus,
    EligibilityResult,
    StructuredSolutionCandidate,
    StructuredSolutionKind,
)
from itou.recommendations.profile import BeneficiaryProfile


# ---------------------------------------------------------------------------
# France Travail education level codes (from API Orientation Usager)
# ---------------------------------------------------------------------------


class FTEducationLevel(enum.StrEnum):
    NO_SCHOOLING = "AFS"
    PRIMARY_TO_4TH = "CP4"
    COMPLETED_4TH = "CFG"
    COMPLETED_3RD = "C3A"
    COMPLETED_2ND_OR_1ST = "C12"
    CAP_BEP = "NV5"
    BAC = "NV4"
    BAC_PLUS_2 = "NV3"
    BAC_PLUS_3_4 = "NV2"
    BAC_PLUS_5_AND_ABOVE = "NV1"


# ---------------------------------------------------------------------------
# Education level sets
# ---------------------------------------------------------------------------

# Level V or below: CAP/BEP and lower.
EDUCATION_LEVEL_V_OR_BELOW = frozenset(
    [
        FTEducationLevel.NO_SCHOOLING,
        FTEducationLevel.PRIMARY_TO_4TH,
        FTEducationLevel.COMPLETED_4TH,
        FTEducationLevel.COMPLETED_3RD,
        FTEducationLevel.CAP_BEP,
    ]
)

# Level IV or below: up to bac (inclusive).
EDUCATION_LEVEL_IV_OR_BELOW = frozenset(
    [
        *EDUCATION_LEVEL_V_OR_BELOW,
        FTEducationLevel.COMPLETED_2ND_OR_1ST,
        FTEducationLevel.BAC,
    ]
)

# ---------------------------------------------------------------------------
# Diagnostic constraint code sets
# ---------------------------------------------------------------------------

HOUSING_DIFFICULTY_CODES = frozenset(["24", "2707", "2708", "2712", "2713", "2715", "2716"])
LITERACY_DIFFICULTY_CODES = frozenset(["20", "21", "22"])
MOBILITY_DIFFICULTY_CODES = frozenset(["6", "7", "8", "40", "2314", "2316"])


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _criterion(code: str, label: str, value: bool | None, *, is_mandatory: bool = True) -> CriterionEvaluation:
    if value is None:
        status = CriterionStatus.UNKNOWN
    else:
        status = CriterionStatus.MET if value else CriterionStatus.NOT_MET
    return CriterionEvaluation(code=code, label=label, status=status, is_mandatory=is_mandatory)


def _n_met(criteria: list[CriterionEvaluation]) -> int:
    return sum(c.status is CriterionStatus.MET for c in criteria)


def evaluate_bool(*, code: str, label: str, value: bool | None, is_mandatory: bool = True) -> CriterionEvaluation:
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_age_range(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    min_age: int | None = None,
    max_age: int | None = None,
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    age = profile.age()
    value = None if age is None else ((min_age is None or age >= min_age) and (max_age is None or age <= max_age))
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_distance(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    candidate: StructuredSolutionCandidate,
    max_distance_km: int,
) -> CriterionEvaluation:
    if profile.coords is None or candidate.coordinates is None:
        return _criterion(code, label, None)
    return _criterion(code, label, distance_in_km(profile.coords, candidate.coordinates) <= max_distance_km)


def evaluate_eligibility_zone(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    candidate: StructuredSolutionCandidate,
) -> CriterionEvaluation:
    if profile.code_insee is None:
        return _criterion(code, label, None)
    value = not candidate.eligibility_zones or profile.code_insee in candidate.eligibility_zones
    return _criterion(code, label, value)


def evaluate_education_level(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    accepted_levels: frozenset[str],
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    value = None if profile.education_level is None else profile.education_level in accepted_levels
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_registration_months(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    min_months: int,
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    months = profile.months_since_registration()
    value = None if months is None else months >= min_months
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_has_housing_difficulty(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    if not profile.diagnostic_constraints:
        return _criterion(code, label, None, is_mandatory=is_mandatory)
    value = any(c.code in HOUSING_DIFFICULTY_CODES for c in profile.diagnostic_constraints)
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_no_literacy_difficulty(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    if not profile.diagnostic_constraints:
        return _criterion(code, label, None, is_mandatory=is_mandatory)
    value = not any(c.code in LITERACY_DIFFICULTY_CODES for c in profile.diagnostic_constraints)
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def evaluate_no_strong_mobility_difficulty(
    *,
    code: str,
    label: str,
    profile: BeneficiaryProfile,
    is_mandatory: bool = True,
) -> CriterionEvaluation:
    if not profile.diagnostic_constraints:
        return _criterion(code, label, None, is_mandatory=is_mandatory)
    value = not any(c.code in MOBILITY_DIFFICULTY_CODES or c.impact == "FORT" for c in profile.diagnostic_constraints)
    return _criterion(code, label, value, is_mandatory=is_mandatory)


def all_mandatory_met(criteria: list[CriterionEvaluation]) -> bool:
    return all(c.status is CriterionStatus.MET or not c.is_mandatory for c in criteria)


def at_least_one_met(criteria: list[CriterionEvaluation]) -> bool:
    return any(c.status is CriterionStatus.MET for c in criteria)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class EligibilityRule(ABC):
    kind: StructuredSolutionKind

    @abstractmethod
    def evaluate(
        self,
        profile: BeneficiaryProfile,
        candidate: StructuredSolutionCandidate,
    ) -> EligibilityResult:
        pass


# ---------------------------------------------------------------------------
# PLIE
# ---------------------------------------------------------------------------


class PLIERule(EligibilityRule):
    kind = StructuredSolutionKind.PLIE
    max_distance_km = 10

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {self.max_distance_km} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=self.max_distance_km,
            ),
            evaluate_eligibility_zone(
                code="zone_eligibilite",
                label="Domicilié sur le territoire couvert par le PLIE",
                profile=profile,
                candidate=candidate,
            ),
            evaluate_age_range(code="age_min", label="Plus de 25 ans", profile=profile, min_age=26),
        ]
        situations = [
            evaluate_registration_months(
                code="deld",
                label="Demandeur d'emploi de longue durée (12 mois minimum)",
                profile=profile,
                min_months=12,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="qpv",
                label="Habitant QPV",
                value=profile.is_qpv_resident,
                is_mandatory=False,
            ),
        ]
        criteria = mandatory + situations
        is_eligible = all_mandatory_met(mandatory) and at_least_one_met(situations)
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(criteria))


# ---------------------------------------------------------------------------
# EPIDE
# ---------------------------------------------------------------------------


class EPIDERule(EligibilityRule):
    kind = StructuredSolutionKind.EPIDE
    max_distance_km = 100

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {self.max_distance_km} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=self.max_distance_km,
            ),
            evaluate_age_range(
                code="age_range",
                label="Jeune de 17 à 25 ans",
                profile=profile,
                min_age=17,
                max_age=25,
            ),
            # French nationality or legal foreign resident is approximated by
            # FT registration (implies right to work).
            evaluate_bool(
                code="right_to_work",
                label="Inscrit à France Travail (autorisation de travailler)",
                value=profile.is_registered_at_france_travail,
            ),
            evaluate_education_level(
                code="education_level",
                label="Niveau de formation inférieur ou égal au niveau V (CAP/BEP)",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_V_OR_BELOW,
            ),
        ]
        optional = [
            evaluate_registration_months(
                code="unemployment_duration",
                label="Inscrit depuis plus de 6 mois",
                profile=profile,
                min_months=6,
                is_mandatory=False,
            ),
        ]
        is_eligible = all_mandatory_met(mandatory)
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(mandatory + optional))


# ---------------------------------------------------------------------------
# E2C
# ---------------------------------------------------------------------------


def _evaluate_age_e2c(profile: BeneficiaryProfile) -> CriterionEvaluation:
    """16–25 ans, OR 26–30 with RQTH."""
    age = profile.age()
    if age is None:
        status = CriterionStatus.UNKNOWN
    elif 16 <= age <= 25:
        status = CriterionStatus.MET
    elif 26 <= age <= 30 and profile.is_rqth_beneficiary:
        status = CriterionStatus.MET
    else:
        status = CriterionStatus.NOT_MET
    return CriterionEvaluation(
        code="age_range",
        label="16–25 ans, ou 26–30 ans avec RQTH",
        status=status,
        is_mandatory=False,
    )


class E2CRule(EligibilityRule):
    kind = StructuredSolutionKind.E2C
    max_distance_km = 10

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {self.max_distance_km} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=self.max_distance_km,
            ),
            evaluate_bool(
                code="registered_ft",
                label="Inscrit à France Travail",
                value=profile.is_registered_at_france_travail,
            ),
            evaluate_education_level(
                code="education_level",
                label="Sans qualification ou premier diplôme jusqu'au bac",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_IV_OR_BELOW,
            ),
        ]
        age_criteria = [_evaluate_age_e2c(profile)]
        is_eligible = all_mandatory_met(mandatory) and at_least_one_met(age_criteria)
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(mandatory + age_criteria))


# ---------------------------------------------------------------------------
# Apprentis d'Auteuil
# ---------------------------------------------------------------------------

_AD_MAX_DISTANCE_KM = 10


class AccompagnementIntensifRule(EligibilityRule):
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_ACCOMPAGNEMENT_INTENSIF

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {_AD_MAX_DISTANCE_KM} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=_AD_MAX_DISTANCE_KM,
            ),
            evaluate_bool(code="rsa", label="Bénéficiaire du RSA", value=profile.is_rsa_beneficiary),
            evaluate_age_range(code="age_range", label="16 à 30 ans", profile=profile, min_age=16, max_age=30),
        ]
        return EligibilityResult(kind=self.kind, is_eligible=all_mandatory_met(mandatory), criteria=tuple(mandatory))


class SkolaRule(EligibilityRule):
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_SKOLA

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {_AD_MAX_DISTANCE_KM} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=_AD_MAX_DISTANCE_KM,
            ),
            evaluate_age_range(code="age_range", label="16 à 30 ans", profile=profile, min_age=16, max_age=30),
            evaluate_education_level(
                code="education_level",
                label="Peu ou pas qualifié",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_IV_OR_BELOW,
            ),
            evaluate_bool(
                code="precarious_situation",
                label="Situation sociale, économique, familiale précaire",
                value=profile.has_declared_constraints,
            ),
        ]
        return EligibilityResult(kind=self.kind, is_eligible=all_mandatory_met(mandatory), criteria=tuple(mandatory))


class BoostInsertionRule(EligibilityRule):
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_BOOST_INSERTION

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {_AD_MAX_DISTANCE_KM} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=_AD_MAX_DISTANCE_KM,
            ),
            evaluate_age_range(code="age_range", label="16 à 29 ans", profile=profile, min_age=16, max_age=29),
        ]
        return EligibilityResult(kind=self.kind, is_eligible=all_mandatory_met(mandatory), criteria=tuple(mandatory))


def _evaluate_potentielles_gender_or_qpv(profile: BeneficiaryProfile) -> CriterionEvaluation:
    """Femme OU résidente QPV."""
    is_woman = profile.civility == "MME" if profile.civility is not None else None
    if is_woman is None and profile.is_qpv_resident is None:
        return CriterionEvaluation(
            code="gender_or_qpv",
            label="Femme ou résidente QPV",
            status=CriterionStatus.UNKNOWN,
            is_mandatory=False,
        )
    met = bool(is_woman) or bool(profile.is_qpv_resident)
    return CriterionEvaluation(
        code="gender_or_qpv",
        label="Femme ou résidente QPV",
        status=CriterionStatus.MET if met else CriterionStatus.NOT_MET,
        is_mandatory=False,
    )


class PotentiellesRule(EligibilityRule):
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_POTENTIELLES

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_distance(
                code="distance",
                label=f"Service à moins de {_AD_MAX_DISTANCE_KM} km",
                profile=profile,
                candidate=candidate,
                max_distance_km=_AD_MAX_DISTANCE_KM,
            ),
            evaluate_age_range(code="age_range", label="16 à 30 ans", profile=profile, min_age=16, max_age=30),
        ]
        optional = [_evaluate_potentielles_gender_or_qpv(profile)]
        is_eligible = all_mandatory_met(mandatory) and at_least_one_met(optional)
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(mandatory + optional))


# ---------------------------------------------------------------------------
# SIAE
# ---------------------------------------------------------------------------


class SIAERule(EligibilityRule):
    """
    At least 1 level-1 criterion, OR at least `level2_threshold` level-2 criteria.
    Default threshold is 3 (ETTI/AI use 2, but sub-type is not tracked in the catalog yet).
    """

    kind = StructuredSolutionKind.SIAE
    level2_threshold: int = 3

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        level1 = [
            evaluate_bool(
                code="rsa",
                label="Bénéficiaire du RSA",
                value=profile.is_rsa_beneficiary,
                is_mandatory=False,
            ),
            # ASS and AAH are not available from FT APIs — omitted.
            evaluate_registration_months(
                code="detld",
                label="Demandeur d'emploi de très longue durée (24 mois+)",
                profile=profile,
                min_months=24,
                is_mandatory=False,
            ),
        ]
        level2 = [
            evaluate_education_level(
                code="education_level",
                label="Niveau d'étude 3 (CAP, BEP) ou infra",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_V_OR_BELOW,
                is_mandatory=False,
            ),
            evaluate_age_range(
                code="senior",
                label="Senior (50 ans et plus)",
                profile=profile,
                min_age=50,
                is_mandatory=False,
            ),
            evaluate_age_range(
                code="young",
                label="Jeune (moins de 26 ans)",
                profile=profile,
                max_age=25,
                is_mandatory=False,
            ),
            # ASE: not available from FT APIs — omitted.
            evaluate_registration_months(
                code="deld",
                label="Demandeur d'emploi de longue durée (12 mois+)",
                profile=profile,
                min_months=12,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="rqth",
                label="Travailleur handicapé (RQTH)",
                value=profile.is_rqth_beneficiary,
                is_mandatory=False,
            ),
            # Parent isolé: not available from FT APIs — omitted.
            evaluate_has_housing_difficulty(
                code="housing",
                label="Sans hébergement ou hébergé ou parcours de rue",
                profile=profile,
                is_mandatory=False,
            ),
            # Réfugié, ZRR, détention: not available from FT APIs — omitted.
            evaluate_bool(
                code="qpv",
                label="Résident QPV",
                value=profile.is_qpv_resident,
                is_mandatory=False,
            ),
            evaluate_no_literacy_difficulty(
                code="literacy",
                label="Maîtrise de la langue française",
                profile=profile,
                is_mandatory=False,
            ),
            evaluate_no_strong_mobility_difficulty(
                code="mobility",
                label="Pas de frein fort à la mobilité",
                profile=profile,
                is_mandatory=False,
            ),
        ]
        is_eligible = at_least_one_met(level1) or _n_met(level2) >= self.level2_threshold
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(level1 + level2))


# ---------------------------------------------------------------------------
# EA (Entreprise adaptée)
# ---------------------------------------------------------------------------


class EARule(EligibilityRule):
    kind = StructuredSolutionKind.EA

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        mandatory = [
            evaluate_bool(
                code="rqth",
                label="Bénéficiaire d'une RQTH (BOETH)",
                value=profile.is_rqth_beneficiary,
            ),
        ]
        additional = [
            evaluate_registration_months(
                code="long_term_unemployment",
                label="Sans emploi depuis au moins 24 mois",
                profile=profile,
                min_months=24,
                is_mandatory=False,
            ),
            # Réfugié, sortant ESAT/ULIS/CFA, détention: not available — omitted.
            evaluate_education_level(
                code="education_level",
                label="Niveau de formation infra 3 ou 3",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_V_OR_BELOW,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="rsa",
                label="Bénéficiaire de minima sociaux (RSA)",
                value=profile.is_rsa_beneficiary,
                is_mandatory=False,
            ),
        ]
        is_eligible = all_mandatory_met(mandatory) and at_least_one_met(additional)
        return EligibilityResult(kind=self.kind, is_eligible=is_eligible, criteria=tuple(mandatory + additional))


# ---------------------------------------------------------------------------
# GEIQ
# ---------------------------------------------------------------------------


def _evaluate_geiq_young_criterion(profile: BeneficiaryProfile) -> CriterionEvaluation:
    """
    Annex 1: under 26, qualification ≤ level 4, no relevant experience (24+ months
    without employment). We approximate "no experience" by long-term unemployment.
    """
    age = profile.age()
    months = profile.months_since_registration()
    if age is None:
        status = CriterionStatus.UNKNOWN
    else:
        status = CriterionStatus.MET if age < 26 and (months is None or months >= 24) else CriterionStatus.NOT_MET
    return CriterionEvaluation(
        code="annex1_young_no_experience",
        label="Jeune de moins de 26 ans sans expérience professionnelle (2 ans+)",
        status=status,
        is_mandatory=False,
    )


class GEIQRule(EligibilityRule):
    """
    GEIQ has no strict eligibility gate: all applicants are eligible if there
    is a matching ROME code (not enforced here — left to the catalog layer).
    Criteria determine the public aid tier:
      - ≥1 annex-1 criterion → 814 €
      - ≥1 annex-2 level-1 criterion AND ≥2 annex-2 level-2 criteria → 1 400 €
    The result is always is_eligible=True; matched_criteria_count drives ranking.
    """

    kind = StructuredSolutionKind.GEIQ

    def evaluate(self, profile: BeneficiaryProfile, candidate: StructuredSolutionCandidate) -> EligibilityResult:
        annex1 = [
            evaluate_registration_months(
                code="annex1_deld",
                label="Éloigné du marché du travail (12 mois+)",
                profile=profile,
                min_months=12,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="annex1_rsa",
                label="Bénéficiaire de minima sociaux (RSA)",
                value=profile.is_rsa_beneficiary,
                is_mandatory=False,
            ),
            # Personnes bénéficiant/sortant d'un dispositif d'insertion: not available — omitted.
            evaluate_bool(
                code="annex1_rqth",
                label="Personne en situation de handicap (RQTH)",
                value=profile.is_rqth_beneficiary,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="annex1_qpv",
                label="Issue de quartier ou zone prioritaire (QPV)",
                value=profile.is_qpv_resident,
                is_mandatory=False,
            ),
            evaluate_age_range(
                code="annex1_senior",
                label="Demandeur d'emploi de 45 ans et plus",
                profile=profile,
                min_age=45,
                is_mandatory=False,
            ),
            # Sortant prison, réfugié, reconversion contrainte: not available — omitted.
            _evaluate_geiq_young_criterion(profile),
        ]
        annex2_level1 = [
            evaluate_bool(
                code="annex2_l1_rsa",
                label="Bénéficiaire du RSA",
                value=profile.is_rsa_beneficiary,
                is_mandatory=False,
            ),
            # ASS, AAH: not available — omitted.
            evaluate_registration_months(
                code="annex2_l1_detld",
                label="Demandeur d'emploi de très longue durée (24 mois+)",
                profile=profile,
                min_months=24,
                is_mandatory=False,
            ),
        ]
        annex2_level2 = [
            evaluate_education_level(
                code="annex2_l2_education",
                label="Niveau d'étude 3 ou infra",
                profile=profile,
                accepted_levels=EDUCATION_LEVEL_V_OR_BELOW,
                is_mandatory=False,
            ),
            evaluate_age_range(
                code="annex2_l2_senior",
                label="Senior (50 ans et plus)",
                profile=profile,
                min_age=50,
                is_mandatory=False,
            ),
            evaluate_age_range(
                code="annex2_l2_young",
                label="Jeune (moins de 26 ans)",
                profile=profile,
                max_age=25,
                is_mandatory=False,
            ),
            # ASE: not available — omitted.
            evaluate_registration_months(
                code="annex2_l2_deld",
                label="Demandeur d'emploi de longue durée (12 mois+)",
                profile=profile,
                min_months=12,
                is_mandatory=False,
            ),
            evaluate_bool(
                code="annex2_l2_rqth",
                label="Travailleur handicapé (RQTH)",
                value=profile.is_rqth_beneficiary,
                is_mandatory=False,
            ),
            # Parent isolé: not available — omitted.
            evaluate_has_housing_difficulty(
                code="annex2_l2_housing",
                label="Sans hébergement ou hébergé",
                profile=profile,
                is_mandatory=False,
            ),
            # Réfugié, ZRR, détention: not available — omitted.
            evaluate_bool(
                code="annex2_l2_qpv",
                label="Résident QPV",
                value=profile.is_qpv_resident,
                is_mandatory=False,
            ),
            evaluate_no_literacy_difficulty(
                code="annex2_l2_literacy",
                label="Maîtrise de la langue française",
                profile=profile,
                is_mandatory=False,
            ),
            evaluate_no_strong_mobility_difficulty(
                code="annex2_l2_mobility",
                label="Pas de frein fort à la mobilité",
                profile=profile,
                is_mandatory=False,
            ),
        ]
        criteria = annex1 + annex2_level1 + annex2_level2
        return EligibilityResult(kind=self.kind, is_eligible=True, criteria=tuple(criteria))
