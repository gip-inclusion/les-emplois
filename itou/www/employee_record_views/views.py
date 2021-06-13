from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http.response import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.encoding import escape_uri_path

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.users.models import JobSeekerProfile
from itou.utils.pagination import pager
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.employee_record_views.forms import (
    NewEmployeeRecordStep1Form,
    NewEmployeeRecordStep2Form,
    NewEmployeeRecordStep3Form,
    NewEmployeeRecordStep4,
    SelectEmployeeRecordStatusForm,
)


# Labels and steps for multi-steps component
STEPS = [
    (
        1,
        "Etat civil",
    ),
    (
        2,
        "Domiciliation",
    ),
    (
        3,
        "Situation",
    ),
    (
        4,
        "Annexe financière",
    ),
    (
        5,
        "Validation",
    ),
]


def update_is_allowed(job_application):
    """
    Check if some steps of the tunnel are reachable or not
    given the current employee record status
    """
    employee_record = job_application.employee_record.first()
    return not employee_record or (employee_record and employee_record.is_updatable)


def siae_is_allowed(job_application, siae):
    return job_application.to_siae == siae


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
        EmployeeRecord.objects.filter(job_application__to_siae=siae)
        .values("status")
        .annotate(cnt=Count("status"))
        .order_by("-status")
    )
    employee_record_badges = {row["status"]: row["cnt"] for row in employee_record_statuses}

    # Set count of each status for badge display
    status_badges = [
        (
            JobApplication.objects.eligible_as_employee_record(siae).count(),
            "info",
        ),
        (employee_record_badges.get(EmployeeRecord.Status.READY, 0), "secondary"),
        (employee_record_badges.get(EmployeeRecord.Status.SENT, 0), "warning"),
        (employee_record_badges.get(EmployeeRecord.Status.REJECTED, 0), "danger"),
        (employee_record_badges.get(EmployeeRecord.Status.PROCESSED, 0), "success"),
    ]

    # Override defaut value (NEW status)
    if form.is_valid():
        status = form.cleaned_data["status"]

    # See comment above on `employee_records_list` var
    if status == EmployeeRecord.Status.NEW:
        data = JobApplication.objects.eligible_as_employee_record(siae)
        employee_records_list = False
    elif status == EmployeeRecord.Status.READY:
        data = EmployeeRecord.objects.ready_for_siae(siae)
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


@login_required
def create(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 1: Name and birth date / place / country of the jobseeker
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    job_application = JobApplication.objects.get(pk=job_application_id)

    if not (update_is_allowed(job_application) and siae_is_allowed(job_application, siae)):
        raise PermissionDenied

    form = NewEmployeeRecordStep1Form(data=request.POST or None, instance=job_application.job_seeker)
    step = 1

    if request.method == "POST" and form.is_valid():
        form.save()

        # Create jobseeker_profile if needed
        employee = job_application.job_seeker
        if not employee.has_jobseeker_profile:
            profile = JobSeekerProfile(user=employee)
            try:
                profile.save()
                profile.update_hexa_address()
            except ValidationError as ex:
                # TODO report error (messages)
                print(f"profile error: {ex}")

        return HttpResponseRedirect(reverse("employee_record_views:create_step_2", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)


@login_required
def create_step_2(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 2: Details and address lookup / check of the employee
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    job_application = JobApplication.objects.get(pk=job_application_id)
    job_seeker = job_application.job_seeker

    # Conditions:
    # - employee record is in an updatable state (if exists)
    # - target job_application / employee record must be linked to given SIAE
    # - a job seeker profile must exist (created in step 1)
    if not all(
        [
            update_is_allowed(job_application),
            siae_is_allowed(job_application, siae),
            job_seeker.has_jobseeker_profile,
        ]
    ):
        raise PermissionDenied

    profile = job_seeker.jobseeker_profile
    form = NewEmployeeRecordStep2Form(data=request.POST or None, instance=job_application.job_seeker)
    maps_url = escape_uri_path(f"https://google.fr/maps/place/{job_application.job_seeker.address_on_one_line}")
    step = 2

    if request.method == "POST" and form.is_valid():
        form.save()
        try:
            profile.update_hexa_address()
        except ValidationError:
            # Impossible to get a valid hexa address:
            # clear previous entry
            profile.clear_hexa_address()

        # Retry until good
        return HttpResponseRedirect(reverse("employee_record_views:create_step_2", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "form": form,
        "profile": job_application.job_seeker.jobseeker_profile,
        "maps_url": maps_url,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)


@login_required
def create_step_3(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 3: Training level, allocations ...
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    job_application = JobApplication.objects.get(pk=job_application_id)
    job_seeker = job_application.job_seeker

    if not job_seeker.has_jobseeker_profile or not all(
        [
            update_is_allowed(job_application),
            siae_is_allowed(job_application, siae),
            job_seeker.jobseeker_profile.hexa_address_filled,
        ]
    ):
        raise PermissionDenied

    step = 3
    profile = job_application.job_seeker.jobseeker_profile
    form = NewEmployeeRecordStep3Form(data=request.POST or None, instance=profile)

    if request.method == "POST" and form.is_valid():
        form.save()
        job_application.refresh_from_db()

        employee_record = None
        if not job_application.employee_record.first():
            employee_record = EmployeeRecord.from_job_application(job_application)
        else:
            employee_record = EmployeeRecord.objects.get(job_application=job_application)

        employee_record.save()

        return HttpResponseRedirect(reverse("employee_record_views:create_step_4", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)


@login_required
def create_step_4(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 4: Financial annex
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    job_application = JobApplication.objects.get(pk=job_application_id)

    if not (update_is_allowed(job_application) and siae_is_allowed(job_application, siae)):
        raise PermissionDenied

    step = 4

    employee_record = EmployeeRecord.objects.get(job_application=job_application)
    form = NewEmployeeRecordStep4(employee_record, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.employee_record.save()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_5", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)


@login_required
def create_step_5(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 5: Summary and validation
    """
    siae = get_current_siae_or_404(request)

    # FIXME: pull-up
    if not siae.can_use_employee_record:
        raise PermissionDenied

    job_application = JobApplication.objects.get(pk=job_application_id)

    if not (update_is_allowed(job_application) and siae_is_allowed(job_application, siae)):
        raise PermissionDenied

    step = 5
    employee_record = EmployeeRecord.objects.get(job_application=job_application)

    if request.method == "POST":
        if employee_record.status in [EmployeeRecord.Status.NEW, EmployeeRecord.Status.REJECTED]:
            employee_record.update_as_ready()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_5", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "employee_record": employee_record,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)


@login_required
def summary(request, employee_record_id, template_name="employee_record/summary.html"):
    """
    Display the summary of a given employee record (no update possible)
    """
    employee_record = get_object_or_404(EmployeeRecord, pk=employee_record_id)
    status = request.GET.get("status")

    context = {
        "employee_record": employee_record,
        "status": status,
    }

    return render(request, template_name, context)
