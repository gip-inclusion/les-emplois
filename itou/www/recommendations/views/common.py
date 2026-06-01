from django.conf import settings


def is_recommendations_advisor(request):
    organization = getattr(request, "current_organization", None)
    return (
        request.from_authorized_prescriber
        and organization is not None
        and organization.code_safir_pole_emploi in settings.ENABLED_RECOMMENDATIONS_SAFIR_CODES
    )
