from django.conf import settings
from django.shortcuts import render

from itou.recommendations.models import Beneficiary
from itou.utils.auth import check_request


@check_request(
    lambda request: (
        request.from_authorized_prescriber
        and request.current_organization.code_safir_pole_emploi in settings.ENABLED_RECOMMENDATIONS_SAFIR_CODES
    )
)
def list_users(request, template_name="recommendations/list.html"):
    # For now we only display Beneficiaries from the current user and organization
    beneficiaries = Beneficiary.objects.filter(
        referent_email=request.user.email, organization_safir=request.current_organization.code_safir_pole_emploi
    )

    return render(request, template_name, {"beneficiaries": beneficiaries})
