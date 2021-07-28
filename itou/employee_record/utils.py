from django.conf import settings

from itou.siaes.models import Siae


# Progressive opening of employee record feature
# ----------------------------------------------
# This is a temporary file !


def siae_eligible_for_progressive_opening(
    siae,
    percentage=settings.EMPLOYEE_RECORD_OPENING_PERCENTAGE,
    curated_siae_ids=settings.EMPLOYEE_RECORD_CUSTOM_SIAE_ID_LIST,
):
    """
    Check if SIAE parameter is:
    - within a percentge of all eligible SIAEs
    - OR within a set of manually chosen SIAEs ("curated")

    Example values for modulo:
    - 100 will get all values
    - 50 will get 50% of all values
    - 1 will get 1% of all values
    """
    # Bypass db queries if in curated list:
    if siae.id in curated_siae_ids:
        return True

    eligible_siaes = Siae.objects.active().filter(kind__in=Siae.ASP_EMPLOYEE_RECORD_KINDS).order_by("id")
    siae_count = eligible_siaes.count()
    limit = int(siae_count * percentage / 100)
    eligible_ids = (eligible_siaes[:limit]).values_list("id", flat=True)

    return siae.id in eligible_ids
