import logging

from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from itou.job_applications.models import JobApplication
from itou.utils.auth import check_user
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.urls import get_safe_url


logger = logging.getLogger(__name__)


def _get_and_lock_received_applications(request, application_ids):
    company = get_current_company_or_404(request)
    applications = list(company.job_applications_received.filter(pk__in=application_ids).select_for_update())
    if mismatch_nb := len(application_ids) - len(applications):
        if mismatch_nb > 1:
            messages.error(
                request, f"{mismatch_nb} candidatures sélectionnées n’existent plus ou ont été transférées."
            )
        else:
            messages.error(request, "Une candidature sélectionnée n’existe plus ou a été transférée.")
    return applications


@check_user(lambda user: user.is_employer)
@require_POST
def archive(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))

    archived_ids = []

    for job_application in applications:
        if job_application.can_be_archived:
            archived_ids.append(job_application.pk)
        elif job_application.archived_at:
            messages.warning(
                request,
                f"La candidature de {job_application.job_seeker.get_full_name()} est déjà archivée.",
                extra_tags="toast",
            )
        else:
            messages.error(
                request,
                (
                    f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être archivée "
                    f"car elle est au statut « {job_application.get_state_display()} »."
                ),
                extra_tags="toast",
            )

    archived_nb = JobApplication.objects.filter(pk__in=archived_ids).update(
        archived_at=timezone.now(),
        archived_by=request.user,
    )

    if archived_nb > 1:
        messages.success(request, f"{archived_nb} candidatures ont bien été archivées.", extra_tags="toast")
    elif archived_nb == 1:
        messages.success(request, "1 candidature a bien été archivée.", extra_tags="toast")

    logger.info(
        "user=%s batch archived %s applications: %s",
        request.user.pk,
        archived_nb,
        ",".join(str(app_uid) for app_uid in archived_ids),
    )
    return HttpResponseRedirect(next_url)
