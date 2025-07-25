import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from itou.job_applications.enums import ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL, JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.auth import check_user
from itou.www.apply.forms import EditHiringDateForm


logger = logging.getLogger(__name__)


@check_user(lambda user: user.is_employer)
def edit_contract_start_date(request, job_application_id, template_name="apply/edit_contract_start_date.html"):
    """
    Update contract start date:
    - at a future point in time
    - if job_application has been accepted

    If there is an approval linked to this job application, change its start date if possible

    This view is kept apart from process or submit views
    """
    queryset = JobApplication.objects.is_active_company_member(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    if not job_application.state.is_accepted:
        PermissionDenied()

    form = EditHiringDateForm(instance=job_application, data=request.POST or None)
    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})

    if request.method == "POST" and form.is_valid():
        form.save()

        messages.success(request, "La période du contrat de travail a bien été mise à jour.", extra_tags="toast")

        logger.info(
            "user=%s changed job_application=%s hiring dates from %s to %s",
            request.user.pk,
            job_application_id,
            [str(form.initial["hiring_start_at"]), str(form.initial["hiring_end_at"])],
            [str(form.cleaned_data["hiring_start_at"]), str(form.cleaned_data["hiring_end_at"])],
        )

        if job_application.approval and job_application.approval.update_start_date(job_application.hiring_start_at):
            messages.success(request, "La date de début du PASS IAE a été fixée à la date de début de contrat.")

        return HttpResponseRedirect(url)

    context = {
        "form": form,
        "job_application": job_application,
        "prev_url": url,
    }

    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer)
def archive_view(request, job_application_id, *, action):
    extra_filters = {}
    if action == "archive":
        action = "archivée"
        archived_at = timezone.now()
        archived_by = request.user
        extra_filters["state__in"] = ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL
    elif action == "unarchive":
        action = "désarchivée"
        archived_at = None
        archived_by = None
    else:
        raise ValueError(action)
    matched = (
        JobApplication.objects.is_active_company_member(request.user)
        .filter(pk=job_application_id, **extra_filters)
        .exclude(state=JobApplicationState.ACCEPTED)
        .update(archived_at=archived_at, archived_by=archived_by)
    )
    if not matched:
        raise Http404
    messages.success(request, f"La candidature a bien été {action}.", extra_tags="toast")
    return HttpResponseRedirect(reverse("apply:details_for_company", args=(job_application_id,)))
