"""Who takes part in the "Prochaines étapes" experiment.

Off by default. Nothing changes for anyone left out: the pages answer 404 and the menu entry is hidden.
"""

from django.conf import settings


def can_view_next_steps(request):
    if not (request.from_employer or request.from_prescriber):
        return False
    if settings.NEXT_STEPS_FOR_EVERYONE or request.user.pk in settings.NEXT_STEPS_USER_PKS:
        return True
    organization = request.current_organization
    if organization is None:
        return False
    if request.from_employer:
        return organization.pk in settings.NEXT_STEPS_COMPANY_PKS
    return organization.pk in settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS
