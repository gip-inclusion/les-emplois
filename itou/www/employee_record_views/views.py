from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.pagination import pager
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.employee_record_views.forms import SelectEmployeeRecordStatusForm


@login_required
def list(request, template_name="employee_record/list.html"):
    """
    Displays a list of employee records for the SIAE
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    form = SelectEmployeeRecordStatusForm(data=request.GET or None)
    status = EmployeeRecord.Status.NEW

    # Employee records are created with a job application object
    # At this stage, new job applications / hirings do not have
    # an associated employee record object
    # Objects in this list can be either:
    # - employee records: iterate on their job application object
    # - basic job applications: iterate as-is
    employee_records_list = True

    navigation_pages = None
    data = None

    # Fetch count of each status for badge display
    status_badges = [
        (
            JobApplication.objects.eligible_as_employee_record(siae).count(),
            "info",
        ),
        (EmployeeRecord.objects.sent_for_siae(siae).count(), "warning"),
        (EmployeeRecord.objects.rejected_for_siae(siae).count(), "danger"),
        (EmployeeRecord.objects.processed_for_siae(siae).count(), "success"),
    ]

    # Override defaut value (NEW status)
    if form.is_valid():
        status = form.cleaned_data["status"]

    # See comment above on `employee_records_list` var
    if status == EmployeeRecord.Status.NEW:
        data = JobApplication.objects.eligible_as_employee_record(siae)
        employee_records_list = False
    elif status == EmployeeRecord.Status.SENT:
        data = EmployeeRecord.objects.sent_for_siae(siae)

    if data:
        navigation_pages = pager(data, request.GET.get("page", 1), items_per_page=10)

    context = {
        "form": form,
        "employee_records_list": employee_records_list,
        "badges": status_badges,
        "navigation_pages": navigation_pages,
    }

    return render(request, template_name, context)
