from itou.cities.cache import get_directory_active_city_ids


def can_access_directory(request):
    organization = getattr(request, "current_organization", None)
    return bool(
        (request.from_employer or request.from_prescriber)
        and organization
        and organization.coords
        and organization.insee_city_id
        and organization.insee_city_id in get_directory_active_city_ids()
    )
