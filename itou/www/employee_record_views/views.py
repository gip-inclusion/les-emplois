from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import formats, safestring

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.employee_record_views.forms import SelectEmployeeRecordStatusForm


@login_required
def list(request, template_name="employee_record/list.html"):
    """
    Displays a list of employee records for the SIAE
    """
    form = SelectEmployeeRecordStatusForm(data=request.POST or None)
    job_applications = None
    siae = get_current_siae_or_404(request)
    status_badges = []

    # Fetch count of each status for badge display
    status_badges.append(
        (
            JobApplication.objects.eligible_as_employee_record(siae).count(),
            "secondary",
        )
    )

    if request.method == "POST" and form.is_valid():
        status = form.cleaned_data["status"]
        if status == EmployeeRecord.Status.NEW:
            job_applications = JobApplication.objects.eligible_as_employee_record(siae)

    context = {
        "form": form,
        "job_applications": job_applications,
        "badges": status_badges,
    }

    return render(request, template_name, context)
