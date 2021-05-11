from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
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

    # Construct badges

    # Badges for "real" employee records
    employee_record_statuses = (
        EmployeeRecord.objects.values("status").annotate(cnt=Count("status")).order_by("-status")
    )
    employee_record_badges = {row["status"]: row["cnt"] for row in employee_record_statuses}

    # Set count of each status for badge display
    status_badges = [
        (
            JobApplication.objects.eligible_as_employee_record(siae).count(),
            "info",
        ),
        (employee_record_badges.get(EmployeeRecord.Status.SENT, 0), "warning"),
        (employee_record_badges.get(EmployeeRecord.Status.REJECTED, 0), "danger"),
        (employee_record_badges.get(EmployeeRecord.Status.PROCESSED, 0), "success"),
    ]

    # Override defaut value (NEW status)
    if form.is_valid():
        status = form.cleaned_data["status"]

    print(status)

    # See comment above on `employee_records_list` var
    if status == EmployeeRecord.Status.NEW:
        data = JobApplication.objects.eligible_as_employee_record(siae)
        employee_records_list = False
    elif status == EmployeeRecord.Status.SENT:
        data = EmployeeRecord.objects.sent_for_siae(siae)
    elif status == EmployeeRecord.Status.REJECTED:
        data = EmployeeRecord.objects.rejected_for_siae(siae)
    elif status == EmployeeRecord.Status.PROCESSED:
        data = EmployeeRecord.objects.processed_for_siae(siae)

    if data:
        navigation_pages = pager(data, request.GET.get("page", 1), items_per_page=10)

    context = {
        "form": form,
        "employee_records_list": employee_records_list,
        "badges": status_badges,
        "navigation_pages": navigation_pages,
    }

    return render(request, template_name, context)
