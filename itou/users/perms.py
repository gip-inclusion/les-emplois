def can_orient_towards_insertion_service(request):
    return bool(request.user.is_authenticated and (request.from_employer or request.from_prescriber))


def can_register_mobilization_event(request):
    return bool(not request.user.is_authenticated or request.from_employer or request.from_prescriber)
