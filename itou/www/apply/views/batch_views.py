import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_xworkflows import models as xwf_models

from itou.companies.models import Company
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.auth import check_user
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import BatchPostponeForm


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


@check_user(lambda user: user.is_employer)
@require_POST
def postpone(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))

    form = BatchPostponeForm(job_seeker_nb=None, data=request.POST)

    if not form.is_valid():
        # This is unlikely since the form is quite simple and the answer field is required
        messages.error(request, "Les candidatures n’ont pas pu être mises en attente.")
        logger.error(
            "user=%s tried to batch postponed %s applications but the form wasn't valid",
            request.user.pk,
            len(applications),
        )
    else:
        postponed_ids = []
        for job_application in applications:
            if job_application.state == JobApplicationState.POSTPONED:
                messages.warning(
                    request,
                    f"La candidature de {job_application.job_seeker.get_full_name()} est déjà mise en attente.",
                    extra_tags="toast",
                )
                continue
            try:
                # After each successful transition, a save() is performed by django-xworkflows.
                job_application.answer = form.cleaned_data["answer"]
                job_application.postpone(user=request.user)
            except xwf_models.InvalidTransitionError:
                messages.error(
                    request,
                    (
                        f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être mise en "
                        f"attente car elle est au statut « {job_application.get_state_display()} »."
                    ),
                    extra_tags="toast",
                )
            else:
                postponed_ids.append(job_application.pk)

        postponed_nb = len(postponed_ids)
        if postponed_nb:
            messages.success(
                request,
                (
                    f"{postponed_nb} candidatures ont bien été mises en attente."
                    if postponed_nb > 1
                    else "La candidature a bien été mise en attente."
                ),
                extra_tags="toast",
            )
        logger.info(
            "user=%s batch postponed %s applications: %s",
            request.user.pk,
            postponed_nb,
            ",".join(str(app_uid) for app_uid in postponed_ids),
        )
    return HttpResponseRedirect(next_url)


@check_user(lambda user: user.is_employer)
@require_POST
def transfer(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    target_company = get_object_or_404(
        Company.objects.filter(pk__in={org.pk for org in request.organizations}),
        pk=request.POST.get("target_company_id"),
    )
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))
    transfered_ids = []
    for job_application in applications:
        try:
            job_application.transfer(user=request.user, target_company=target_company)
            transfered_ids.append(job_application.pk)
        except (ValidationError, xwf_models.InvalidTransitionError):
            error_msg = f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être transférée"
            if not job_application.transfer.is_available():
                error_msg += f" car elle est au statut « {job_application.get_state_display()} »."
            else:
                error_msg += "."
            messages.error(request, error_msg, extra_tags="toast")

    transfered_nb = len(transfered_ids)
    if transfered_nb > 1:
        messages.success(request, f"{transfered_nb} candidatures ont bien été transférées.", extra_tags="toast")
    elif transfered_nb == 1:
        messages.success(request, "1 candidature a bien été transférée.", extra_tags="toast")
    logger.info(
        "user=%s batch transfered %s applications: %s",
        request.user.pk,
        transfered_nb,
        ",".join(str(app_uid) for app_uid in transfered_ids),
    )
    return HttpResponseRedirect(next_url)
