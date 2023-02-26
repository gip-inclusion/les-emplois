from collections import Counter


def geiq_allowance_amount(is_authorized_prescriber, administrative_criteria) -> int:
    """Amount of granted allowance for job seeker.

    Calculated in function of:
        - author kind
        - number, annex and level of administrative criteria.
    Currently, only 3 amounts possible:
        - 0
        - 814EUR
        - 1400EUR
    """

    # Even when no criteria in the diagnosis
    if is_authorized_prescriber:
        return 1400

    # Count by annex
    annex_cnt = Counter(c.annex for c in administrative_criteria)

    # Only annex 2 administrative criteria have a level defined
    level_cnt = Counter(c.level for c in administrative_criteria if c.level)

    # At least one level 1 criterion or at least two level 2 criteria
    if level_cnt["1"] > 0 or level_cnt["2"] > 1:
        return 1400

    # Criteria in both annex ("1+2") must be counted as annex 1
    if annex_cnt["1"] + annex_cnt["1+2"] > 0:
        return 814

    return 0
