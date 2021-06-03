from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http.response import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.users.models import JobSeekerProfile
from itou.utils.pagination import pager
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.employee_record_views.forms import (
    NewEmployeeRecordStep1,
    NewEmployeeRecordStep2,
    NewEmployeeRecordStep3,
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
    form = NewEmployeeRecordStep1(data=request.POST or None, instance=job_application.job_seeker)
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
                print(f"error: {ex}")

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
    profile = job_application.job_seeker.jobseeker_profile
    form = NewEmployeeRecordStep2(data=request.POST or None, instance=job_application.job_seeker)
    maps_url = f"https://google.fr/maps/place/{job_application.job_seeker.address_on_one_line}"
    step = 2

    if request.method == "POST" and form.is_valid():
        form.save()
        try:
            profile.update_hexa_address()
        except ValidationError as ex:
            # TODO report error (messages)
            print(f"error: {ex}")

        # Loop on itself until good
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
    step = 3
    job_application = JobApplication.objects.get(pk=job_application_id)
    profile = job_application.job_seeker.jobseeker_profile
    form = NewEmployeeRecordStep3(data=request.POST or None, instance=profile)

    if request.method == "POST" and form.is_valid():
        form.save()
        job_application.refresh_from_db()
        # FIXME try
        EmployeeRecord.from_job_application(job_application).save()
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
    step = 4
    job_application = JobApplication.objects.get(pk=job_application_id)
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
    step = 5
    job_application = JobApplication.objects.get(pk=job_application_id)
    employee_record = EmployeeRecord.objects.get(job_application=job_application)

    if request.method == "POST":
        if employee_record.status == EmployeeRecord.Status.NEW:
            employee_record.update_as_ready()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_5", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "employee_record": employee_record,
        "steps": STEPS,
        "step": step,
    }

    return render(request, template_name, context)
