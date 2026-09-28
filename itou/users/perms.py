from itou.users.models import JobSeekerAssignment


def can_orient_towards_insertion_service(request):
    return bool(request.user.is_authenticated and (request.from_employer or request.from_prescriber))


def can_register_mobilization_event(request):
    return bool(not request.user.is_authenticated or request.from_employer or request.from_prescriber)


def add_user_can_view_personal_information(objects, can_view, user_attr="job_seeker"):
    for obj in objects:
        obj.user_can_view_personal_information = can_view(getattr(obj, user_attr))


def can_fill_pro_support_report(request):
    return bool(request.from_employer and request.from_iae_actor)


def can_view_pro_support_report(request, report):
    if request.from_employer:
        return report.company_id == request.current_organization.pk
    if request.from_prescriber:
        return (
            JobSeekerAssignment.objects.assigned_to(
                request.user, request.current_organization, from_all_coworkers=True
            )
            .filter(job_seeker_id=report.job_seeker_id)
            .exists()
        )
    return False
