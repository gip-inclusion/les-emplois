from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http.response import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_safe

from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.users.models import JobSeekerProfile
from itou.utils.pagination import pager
from itou.utils.perms.employee_record import can_create_employee_record, siae_is_allowed
from itou.utils.perms.siae import get_current_siae_or_404
from itou.www.employee_record_views.forms import (
    NewEmployeeRecordStep1Form,
    NewEmployeeRecordStep2Form,
    NewEmployeeRecordStep3Form,
    NewEmployeeRecordStep4,
    SelectEmployeeRecordStatusForm,
)

from .enums import EmployeeRecordOrder


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


# Views


@login_required
@require_safe
def list_employee_records(request, template_name="employee_record/list.html"):
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    form = SelectEmployeeRecordStatusForm(data=request.GET)

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
        EmployeeRecord.objects.for_siae(siae).values("status").annotate(cnt=Count("status")).order_by("-status")
    )
    employee_record_badges = {row["status"]: row["cnt"] for row in employee_record_statuses}

    eligibible_job_applications = JobApplication.objects.eligible_as_employee_record(siae)

    # Set count of each status for badge display
    status_badges = [
        (
            eligibible_job_applications.count(),
            "info",
        ),
        (employee_record_badges.get(Status.READY, 0), "secondary"),
        (employee_record_badges.get(Status.SENT, 0), "warning"),
        (employee_record_badges.get(Status.REJECTED, 0), "danger"),
        (employee_record_badges.get(Status.PROCESSED, 0), "success"),
        (employee_record_badges.get(Status.DISABLED, 0), "emploi-lightest"),
    ]

    # See comment above on `employee_records_list` var
    form.full_clean()  # We do not use is_valid to validate each field independently
    status = Status(form.cleaned_data.get("status") or Status.NEW)
    order_by = EmployeeRecordOrder(form.cleaned_data.get("order") or EmployeeRecordOrder.HIRING_START_AT_DESC)

    job_application_order_by = {
        EmployeeRecordOrder.NAME_ASC: ("job_seeker__last_name", "job_seeker__first_name"),
        EmployeeRecordOrder.NAME_DESC: ("-job_seeker__last_name", "-job_seeker__first_name"),
        EmployeeRecordOrder.HIRING_START_AT_ASC: ("hiring_start_at",),
        EmployeeRecordOrder.HIRING_START_AT_DESC: ("-hiring_start_at",),
    }[order_by]
    employee_record_order_by = tuple(
        f"-job_application__{order_by_item[1:]}" if order_by_item[0] == "-" else f"job_application__{order_by_item}"
        for order_by_item in job_application_order_by
    )

    # Not needed every time (not pulled-up), and DRY here
    base_query = EmployeeRecord.objects.full_fetch().order_by(*employee_record_order_by)
    has_outdated_date = False

    if status == Status.NEW:
        # Browse to get only the linked employee record in "new" state
        data = eligibible_job_applications.order_by(*job_application_order_by)
        for item in data:
            item.has_outdated_date = (
                item.approval.suspension_set.filter(siae=siae).exists()
                or item.approval.prolongation_set.filter(declared_by_siae=siae).exists()
            )
            has_outdated_date |= item.has_outdated_date

            for e in item.employee_record.all():
                if e.status == Status.NEW:
                    item.employee_record_new = e
                    break
        employee_records_list = False
    else:
        data = base_query.filter(status=status).for_siae(siae)

    if data:
        navigation_pages = pager(data, request.GET.get("page", 1), items_per_page=10)

    context = {
        "form": form,
        "employee_records_list": employee_records_list,
        "badges": status_badges,
        "navigation_pages": navigation_pages,
        "feature_availability_date": EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
        "has_outdated_date": has_outdated_date,
        "ordered_by_label": order_by.label,
    }

    return render(request, template_name, context)


@login_required
def create(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 1: Name and birth date / place / country of the jobseeker
    """
    job_application = can_create_employee_record(request, job_application_id)
    form = NewEmployeeRecordStep1Form(data=request.POST or None, instance=job_application.job_seeker)

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_2", args=(job_application.pk,)))

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": 1,
    }

    return render(request, template_name, context)


@login_required
def create_step_2(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 2: Details and address lookup / check of the employee
    """
    job_application = can_create_employee_record(request, job_application_id)
    job_seeker = job_application.job_seeker
    profile, _ = JobSeekerProfile.objects.get_or_create(user=job_seeker)
    address_filled = job_seeker.post_code and job_seeker.address_line_1
    form = NewEmployeeRecordStep2Form(data=request.POST or None, instance=profile)

    # Perform a geolocation of the user address if possible:
    # - success : prefill form with geolocated data
    # - failure : display actual address and let user fill the form
    if not profile.hexa_address_filled and address_filled:
        try:
            # Attempt to create a job seeker profile with an address prefilled
            profile.update_hexa_address()
        except ValidationError:
            # Not a big deal anymore, let user fill address form
            profile.clear_hexa_address()

    # At this point, a job seeker profile was created

    if request.method == "POST":
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(
                reverse(
                    "employee_record_views:create_step_2",
                    args=(job_application.id,),
                )
            )
        else:
            profile.clear_hexa_address()

    context = {
        "job_application": job_application,
        "form": form,
        "profile": profile,
        "address_filled": address_filled,
        "job_seeker": job_seeker,
        "steps": STEPS,
        "step": 2,
    }

    return render(request, template_name, context)


@login_required
def create_step_3(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 3: Training level, allocations ...
    """
    job_application = can_create_employee_record(request, job_application_id)
    job_seeker = job_application.job_seeker

    # At this point, a job seeker profile must have been created
    if not job_seeker.has_jobseeker_profile:
        raise PermissionDenied

    profile = job_seeker.jobseeker_profile

    if not profile.hexa_address_filled:
        raise PermissionDenied

    form = NewEmployeeRecordStep3Form(data=request.POST or None, instance=profile)

    if request.method == "POST" and form.is_valid():
        form.save()
        job_application.refresh_from_db()
        employee_record = None

        try:
            if not job_application.employee_record.exclude(status=Status.DISABLED).first():
                employee_record = EmployeeRecord.from_job_application(job_application)
            else:
                employee_record = EmployeeRecord.objects.exclude(status=Status.DISABLED).get(
                    job_application=job_application
                )

            employee_record.save()

            return HttpResponseRedirect(reverse("employee_record_views:create_step_4", args=(job_application.id,)))
        except ValidationError as ex:
            # If anything goes wrong during employee record creation,
            #  catch it and show error to the user
            messages.error(
                request,
                f"Il est impossible de créer cette fiche salarié pour la raison suivante : {ex.message}.",
            )

    context = {
        "job_application": job_application,
        "form": form,
        "is_registered_to_pole_emploi": bool(job_application.job_seeker.pole_emploi_id),
        "steps": STEPS,
        "step": 3,
    }

    return render(request, template_name, context)


@login_required
def create_step_4(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 4: Financial annex
    """
    job_application = can_create_employee_record(request, job_application_id)

    if not job_application.job_seeker.has_jobseeker_profile:
        raise PermissionDenied

    employee_record = (
        EmployeeRecord.objects.full_fetch()
        .exclude(status=Status.DISABLED)
        .select_related("job_application__to_siae__convention")
        .get(job_application=job_application)
    )
    form = NewEmployeeRecordStep4(employee_record, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.employee_record.save()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_5", args=(job_application.id,)))

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": 4,
    }

    return render(request, template_name, context)


@login_required
def create_step_5(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 5: Summary and validation
    """
    job_application = can_create_employee_record(request, job_application_id)

    if not job_application.job_seeker.has_jobseeker_profile:
        raise PermissionDenied

    employee_record = get_object_or_404(
        EmployeeRecord.objects.full_fetch().exclude(status=Status.DISABLED), job_application=job_application
    )

    if request.method == "POST":
        if employee_record.status in [Status.NEW, Status.REJECTED, Status.DISABLED]:
            employee_record.update_as_ready()
        return HttpResponseRedirect(reverse("employee_record_views:create_step_5", args=(job_application.pk,)))

    context = {
        "employee_record": employee_record,
        "job_application": job_application,
        "steps": STEPS,
        "step": 5,
    }

    return render(request, template_name, context)


@login_required
def summary(request, employee_record_id, template_name="employee_record/summary.html"):
    """
    Display the summary of a given employee record (no update possible)
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    query_base = EmployeeRecord.objects.full_fetch().exclude(status=Status.DISABLED)
    employee_record = get_object_or_404(query_base, pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    status = request.GET.get("status")

    context = {
        "employee_record": employee_record,
        "status": status,
    }

    return render(request, template_name, context)


@login_required
def disable(request, employee_record_id, template_name="employee_record/disable.html"):
    """
    Display the form to disable a given employee record
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    query_base = EmployeeRecord.objects.full_fetch().exclude(status=Status.DISABLED)
    employee_record = get_object_or_404(query_base, pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    status = request.GET.get("status")
    list_url = reverse("employee_record_views:list")
    back_url = f"{ list_url }?status={ status }"

    if not employee_record.can_be_disabled:
        messages.error(request, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE)
        return HttpResponseRedirect(back_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        employee_record.update_as_disabled()
        messages.success(request, "La fiche salarié a bien été désactivée.")
        return HttpResponseRedirect(back_url)

    context = {
        "employee_record": employee_record,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def reactivate(request, employee_record_id, template_name="employee_record/reactivate.html"):
    """
    Display the form to reactivate a given employee record
    """
    siae = get_current_siae_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    query_base = EmployeeRecord.objects.full_fetch()
    employee_record = get_object_or_404(query_base, pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    list_url = reverse("employee_record_views:list")
    back_url = f"{ list_url }?status={ Status.DISABLED }"

    if employee_record.status != Status.DISABLED:
        messages.error(request, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE)
        return HttpResponseRedirect(back_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        try:
            employee_record.update_as_new()
            messages.success(request, "La fiche salarié a bien été réactivée.")
            return HttpResponseRedirect(back_url)
        except ValidationError as ex:
            messages.error(
                request,
                f"Il est impossible de réactiver cette fiche salarié pour la raison suivante : {ex.message}.",
            )

    context = {
        "employee_record": employee_record,
        "back_url": back_url,
    }
    return render(request, template_name, context)
