from django.conf import settings

from itou.cities.cache import get_directory_active_city_ids


def can_access_directory(request):
    if not (request.from_employer or request.from_authorized_prescriber):
        return False
    organization = request.current_organization
    directory_is_active = (
        settings.PROFESSIONAL_DIRECTORY_ACTIVE
        and organization.insee_city_id
        and organization.insee_city_id in get_directory_active_city_ids()
    )
    return bool(directory_is_active and organization.coords)
