from dataclasses import dataclass

from itou.geo.utils import distance_in_km
from itou.recommendations.criteria import EligibilityResult, StructuredSolutionCandidate, StructuredSolutionKind
from itou.recommendations.profile import BeneficiaryProfile
from itou.recommendations.rules import (
    AccompagnementIntensifRule,
    BoostInsertionRule,
    E2CRule,
    EARule,
    EligibilityRule,
    EPIDERule,
    GEIQRule,
    PLIERule,
    PotentiellesRule,
    SIAERule,
    SkolaRule,
)


_ALL_RULES: dict[StructuredSolutionKind, EligibilityRule] = {
    rule.kind: rule
    for rule in (
        PLIERule(),
        EPIDERule(),
        E2CRule(),
        AccompagnementIntensifRule(),
        SkolaRule(),
        BoostInsertionRule(),
        PotentiellesRule(),
        SIAERule(),
        EARule(),
        GEIQRule(),
    )
}


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    candidate: StructuredSolutionCandidate
    eligibility: EligibilityResult


def recommend(
    profile: BeneficiaryProfile,
    candidates: list[StructuredSolutionCandidate],
) -> list[RecommendationResult]:
    """
    Return the list of eligible structured solutions for the given beneficiary,
    sorted by:
      1. Number of matched criteria descending (best match first).
      2. Distance from the beneficiary's address ascending (closest first),
         when coordinates are available.
    """
    results = []
    for candidate in candidates:
        rule = _ALL_RULES.get(candidate.kind)
        if rule is None:
            continue
        eligibility = rule.evaluate(profile, candidate)
        if eligibility.is_eligible:
            results.append(RecommendationResult(candidate=candidate, eligibility=eligibility))

    results.sort(key=_sort_key(profile))
    return results


def _sort_key(profile: BeneficiaryProfile):
    def key(r: RecommendationResult):
        if profile.coords is None or r.candidate.coordinates is None:
            dist = float("inf")
        else:
            dist = distance_in_km(profile.coords, r.candidate.coordinates)
        return (-r.eligibility.matched_criteria_count, dist)

    return key
