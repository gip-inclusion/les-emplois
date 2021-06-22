from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.perms.siae import get_current_siae_or_404


def tunnel_step_is_allowed(job_application):
    """
    Check if some steps of the tunnel are reachable or not
    given the current employee record status
    """
    # Count is cheaper than fetching nothing
    no_employee_record_yet = job_application.employee_record.count() == 0
    if no_employee_record_yet:
        return True

    # There is an employee record
    employee_record = job_application.employee_record.first()

    return employee_record.status in [
        EmployeeRecord.Status.NEW,
        EmployeeRecord.Status.READY,
        EmployeeRecord.Status.REJECTED,
    ]


def siae_is_allowed(job_application, siae):
    """
    SIAEs are only allowed to see "their" employee records
    """
    return job_application.to_siae == siae


def can_create_employee_record(request, job_application_id=None):
    """
    Check if conditions / permissions are set to use the employee record views
    If a valid job_application_id is given, return a full-fledged
    JobApplication object reusable in view (skip one extra DB query)
    """
    # SIAEs only
    siae = get_current_siae_or_404(request)

    # SIAE is eligible to employee record ?
    if not siae.can_use_employee_record:
        raise PermissionDenied

    if job_application_id:
        # We want to reuse a job application in view, but first check that all is ok
        job_application = get_object_or_404(
            JobApplication.objects.select_related(
                "approval",
                "job_seeker",
                "job_seeker__jobseeker_profile",
            ),
            pk=job_application_id,
        )

        if not (siae_is_allowed(job_application, siae) and tunnel_step_is_allowed(job_application)):
            raise PermissionDenied

        # Finally, the reusable Holy Grail
        return job_application

    # All checks performed, without asking for a job application object
    return None
