from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from itou.job_applications.models import JobApplication
from itou.www.apply.forms import EditHiringDateForm


@login_required
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
    url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})

    if request.method == "POST" and form.is_valid():
        form.save()

        messages.success(request, "La période du contrat de travail a été mise à jour.")

        if job_application.approval and job_application.approval.update_start_date(job_application.hiring_start_at):
            messages.success(request, "La date de début du PASS IAE a été fixée à la date de début de contrat.")

        return HttpResponseRedirect(url)

    context = {
        "form": form,
        "job_application": job_application,
        "prev_url": url,
    }

    return render(request, template_name, context)
