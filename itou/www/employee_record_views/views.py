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


# Information message after selecting an employee record status
INFO_MSG_NEW = (
    "Vous trouverez ici les candidatures validées à partir desquelles vous devez créér de nouvelles fiches salarié"
)
INFO_MSG_SENT = (
    "Vous trouverez ici les fiches salarié complétées et envoyées à l'ASP. "
    "A ce stade, et en attendant un retour de l'ASP, seule la visualisation des informations de la fiche est possible"
)
INFO_MSG_REJECTED = (
    "Vous trouverez ici les fiches salarié envoyées à l'ASP et retournées avec une erreur. "
    "Vous pouvez modifier les fiches en erreur et les envoyer à nouveau"
)
INFO_MSG_ACCEPTED = (
    "Vous trouverez ici les fiches salarié envoyées et validées par l'ASP. "
    "Aucune action ultérieure n'est possible à ce stade, mais vous pouvez consulter les informations validées par l'ASP"
)


@login_required
def list(request, template_name="employee_record/list.html"):
    """
    Displays a list of employee records for the SIAE
    """
    form = SelectEmployeeRecordStatusForm(data=request.POST or None)
    job_applications = None
    employee_records = None
    siae = get_current_siae_or_404(request)

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

    if request.method == "POST" and form.is_valid():
        status = form.cleaned_data["status"]
        message = {
            EmployeeRecord.Status.NEW: INFO_MSG_NEW,
            EmployeeRecord.Status.SENT: INFO_MSG_SENT,
            EmployeeRecord.Status.REJECTED: INFO_MSG_REJECTED,
            EmployeeRecord.Status.PROCESSED: INFO_MSG_ACCEPTED,
        }.get(status)

        if message:
            messages.info(request, message)

        if status == EmployeeRecord.Status.NEW:
            job_applications = JobApplication.objects.eligible_as_employee_record(siae)
        elif status == EmployeeRecord.Status.SENT:
            employee_records = EmployeeRecord.objects.sent_for_siae(siae)

    context = {
        "form": form,
        "job_applications": job_applications,
        "employee_records": employee_records,
        "badges": status_badges,
    }

    return render(request, template_name, context)


@login_required
def create_employee_record(request):
    pass
