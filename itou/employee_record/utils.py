from django.conf import settings
from django.db.models import F, Q

from itou.siaes.models import Siae


# Progressive opening of employee record feature
# ----------------------------------------------
# This is a temporary file !


def siae_eligible_for_progressive_opening(
    siae, modulo=settings.EMPLOYEE_RECORD_ASP_ID_MODULO, curated_siaes=settings.EMPLOYEE_RECORD_CUSTOM_ASP_ID_LIST
):
    """
    Check if SIAE parameter is:
    - within a modulo range on the `convention.asp_id` field (a value of 100 will get all values)
    - within a set of manually chosen SIAE ("curated")
    """

    # Modulo 100 on asp_id part:
    modulo_q = Q(idmod__lt=modulo)

    # Add "curated" SIAE
    curated_siaes_q = Q(id__in=curated_siaes)

    # Compose Q objects:
    siae_filter = (
        Siae.objects.annotate(idmod=F("convention__asp_id") % 100)
        .filter(modulo_q | curated_siaes_q)
        .values_list("id", flat=True)
    )

    return siae.id in siae_filter
