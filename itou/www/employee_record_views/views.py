from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Exists, OuterRef
from django.http.response import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_safe
from formtools.wizard.views import NamedUrlSessionWizardView

from itou.approvals.models import Approval, Prolongation, Suspension
from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.users.enums import LackOfNIRReason, UserKind
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.employee_record import can_create_employee_record, siae_is_allowed
from itou.www.employee_record_views.forms import (
    AddEmployeeRecordChooseApprovalForm,
    AddEmployeeRecordChooseEmployeeForm,
    EmployeeRecordFilterForm,
    NewEmployeeRecordStep1Form,
    NewEmployeeRecordStep2Form,
    NewEmployeeRecordStep3Form,
    NewEmployeeRecordStep4,
    SelectEmployeeRecordStatusForm,
)

from ...users.models import User
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


def _show_add_choose_approval_form(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step("choose-employee") or {}
    return bool(cleaned_data.get("employee"))


class AddView(LoginRequiredMixin, NamedUrlSessionWizardView):
    template_name = "employee_record/add.html"
    form_list = [
        ("choose-employee", AddEmployeeRecordChooseEmployeeForm),
        ("choose-approval", AddEmployeeRecordChooseApprovalForm),
    ]
    condition_dict = {
        "choose-approval": _show_add_choose_approval_form,
    }

    def dispatch(self, request, *args, **kwargs):
        # Do LoginRequiredMixin.dispatch() here so we get the 404 and the redirect before the PermissionDenied
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        self.company = get_current_company_or_404(request)
        if not self.company.can_use_employee_record:
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, step=None):
        hiring_of_the_company = JobApplication.objects.accepted().filter(to_company=self.company)
        if step == "choose-employee":
            return {"employees": hiring_of_the_company.get_unique_fk_objects("job_seeker")}
        elif step == "choose-approval":
            employee = User.objects.get(
                pk=self.get_cleaned_data_for_step("choose-employee")["employee"], kind=UserKind.JOB_SEEKER
            )
            return {
                "employee": employee,
                # FIXME(rsebille): Remove the approvals `pk_in` filter once employee records creation
                #  does not require a job applications.
                "approvals": employee.approvals.filter(
                    pk__in=[a.pk for a in hiring_of_the_company.get_unique_fk_objects("approval")]
                ).order_by("-end_at"),
            }
        return {}

    def done(self, form_list, *args, **kwargs):
        approval = Approval.objects.get(
            pk=self.get_all_cleaned_data()["approval"], user=self.get_all_cleaned_data()["employee"]
        )
        try:
            employee_record = EmployeeRecord.objects.for_company(self.company).get(approval_number=approval.number)
        except EmployeeRecord.DoesNotExist:  # Send to the creation tunnel with the last accepted job application
            job_application = (
                JobApplication.objects.filter(to_company=self.company, approval=approval)
                .accepted()
                .with_accepted_at()
                .latest("accepted_at")
            )
            return HttpResponseRedirect(
                reverse("employee_record_views:create", kwargs={"job_application_id": job_application.pk})
            )
        else:
            if employee_record.status == Status.NEW:  # Should be filled, send to the creation tunnel
                return HttpResponseRedirect(
                    reverse(
                        "employee_record_views:create",
                        kwargs={"job_application_id": employee_record.job_application.pk},
                    )
                    + "?back_url="
                    + reverse("employee_record_views:add", kwargs={"step": "choose-employee"})
                )
            else:  # An employee record exists, show the summary
                return HttpResponseRedirect(
                    reverse("employee_record_views:summary", kwargs={"employee_record_id": employee_record.pk})
                )


@login_required
@require_safe
def list_employee_records(request, template_name="employee_record/list.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    filters_form = EmployeeRecordFilterForm(
        JobApplication.objects.accepted().filter(to_company=siae).get_unique_fk_objects("job_seeker"),
        data=request.GET,
    )
    filters_form.full_clean()

    form = SelectEmployeeRecordStatusForm(data=request.GET)
    form.full_clean()  # We do not use is_valid to validate each field independently
    status = Status(form.cleaned_data.get("status") or Status.NEW)
    order_by = EmployeeRecordOrder(form.cleaned_data.get("order") or EmployeeRecordOrder.HIRING_START_AT_DESC)

    # Prepare .order_by() parameters for JobApplication() and EmployeeRecord()
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

    # Construct badges

    employee_record_badges = {
        row["status"]: row["cnt"]
        for row in EmployeeRecord.objects.for_company(siae).values("status").annotate(cnt=Count("status"))
    }

    eligible_job_applications = JobApplication.objects.eligible_as_employee_record(siae)
    if status == Status.NEW:
        # When showing NEW job applications, we need more infos
        eligible_job_applications = eligible_job_applications.annotate(
            has_suspension=Exists(Suspension.objects.filter(siae=siae, approval__jobapplication__pk=OuterRef("pk"))),
            has_prolongation=Exists(
                Prolongation.objects.filter(declared_by_siae=siae, approval__jobapplication__pk=OuterRef("pk"))
            ),
        ).order_by(*job_application_order_by)

    # Set count of each status for badge display
    status_badges = [
        (
            # Don't use count() since we also need the list when status is NEW
            len(eligible_job_applications) if status == Status.NEW else eligible_job_applications.count(),
            "bg-info",
        ),
        (employee_record_badges.get(Status.READY, 0), "bg-secondary"),
        (employee_record_badges.get(Status.SENT, 0), "bg-warning"),
        (employee_record_badges.get(Status.REJECTED, 0), "bg-danger"),
        (employee_record_badges.get(Status.PROCESSED, 0), "bg-success"),
        (employee_record_badges.get(Status.DISABLED, 0), "bg-emploi-lightest text-primary"),
    ]

    # Employee records are created with a job application object.
    # At this stage, job applications do not have an associated employee record.
    # Objects in this list can be either:
    # - employee records: iterate on their job application object
    # - job applications: iterate as-is
    employee_records_list = True
    need_manual_regularization = False

    if status == Status.NEW:
        # Browse to get only the linked employee record in "new" state
        data = eligible_job_applications
        if job_seekers := filters_form.cleaned_data.get("job_seekers"):
            # The queryset was already evaluated for badges, so it's faster to iterate because of the non-trivial query
            data = [ja for ja in data if str(ja.job_seeker_id) in job_seekers]

        for item in data:
            item.date_were_not_transmitted = item.has_suspension or item.has_prolongation
            item.nir_tally_params = f"?jobapplication={item.pk}"
            for e in item.employee_record.all():
                item.date_were_not_transmitted = False
                if e.status == Status.NEW:
                    item.employee_record_new = e
                    item.nir_tally_params = f"?employeerecord={e.pk}"
                    break
            # Flag for the global message alert
            need_manual_regularization |= item.date_were_not_transmitted
            need_manual_regularization |= (
                item.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
            )

        employee_records_list = False
    else:
        data = (
            EmployeeRecord.objects.full_fetch()
            .for_company(siae)
            .filter(status=status)
            .order_by(*employee_record_order_by)
        )
        if job_seekers := filters_form.cleaned_data.get("job_seekers"):
            data = data.filter(job_application__job_seeker__in=job_seekers)

    context = {
        "form": form,
        "filters_form": filters_form,
        "employee_records_list": employee_records_list,
        "badges": status_badges,
        "navigation_pages": pager(data, request.GET.get("page"), items_per_page=10),
        "feature_availability_date": EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
        "need_manual_regularization": need_manual_regularization,
        "ordered_by_label": order_by.label,
        "matomo_custom_title": "Fiches salarié ASP",
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
    query_param = f"?status={request.GET.get('status')}" if request.GET.get("status") else ""

    if request.method == "POST" and form.is_valid():
        form.save()
        return HttpResponseRedirect(
            reverse("employee_record_views:create_step_2", args=(job_application.pk,)) + query_param
        )

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": 1,
        "matomo_custom_title": "Nouvelle fiche salarié ASP - Étape 1",
        "back_url": request.GET.get("back_url"),
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
    profile = job_seeker.jobseeker_profile
    address_filled = job_seeker.post_code and job_seeker.address_line_1
    form = NewEmployeeRecordStep2Form(data=request.POST or None, instance=profile)
    query_param = f"?status={request.GET.get('status')}" if request.GET.get("status") else ""

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
                + query_param
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
        "matomo_custom_title": "Nouvelle fiche salarié ASP - Étape 2",
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
    query_param = f"?status={request.GET.get('status')}" if request.GET.get("status") else ""

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

        if job_application.employee_record.exists():
            # The EmployeeRecord() object exists, usually its status should be NEW or REJECTED
            return HttpResponseRedirect(
                reverse("employee_record_views:create_step_4", args=(job_application.id,)) + query_param
            )

        # The EmployeeRecord() object doesn't exist, so we create one from the job application
        try:
            employee_record = EmployeeRecord.from_job_application(job_application)
            employee_record.save()
        except ValidationError as ex:
            # If anything goes wrong during employee record creation, catch it and show error to the user
            messages.error(
                request,
                f"Il est impossible de créer cette fiche salarié pour la raison suivante : {ex.message}.",
            )
        else:
            return HttpResponseRedirect(
                reverse("employee_record_views:create_step_4", args=(job_application.id,)) + query_param
            )

    context = {
        "job_application": job_application,
        "form": form,
        "is_registered_to_pole_emploi": bool(job_application.job_seeker.jobseeker_profile.pole_emploi_id),
        "steps": STEPS,
        "step": 3,
        "matomo_custom_title": "Nouvelle fiche salarié ASP - Étape 3",
    }

    return render(request, template_name, context)


@login_required
def create_step_4(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 4: Financial annex
    """
    job_application = can_create_employee_record(request, job_application_id)
    query_param = f"?status={request.GET.get('status')}" if request.GET.get("status") else ""

    if not job_application.job_seeker.has_jobseeker_profile:
        raise PermissionDenied

    employee_record = (
        job_application.employee_record.full_fetch()
        .select_related("job_application__to_company__convention")
        .latest("created_at")
    )
    form = NewEmployeeRecordStep4(employee_record, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.employee_record.save()
        return HttpResponseRedirect(
            reverse("employee_record_views:create_step_5", args=(job_application.id,)) + query_param
        )

    context = {
        "job_application": job_application,
        "form": form,
        "steps": STEPS,
        "step": 4,
        "matomo_custom_title": "Nouvelle fiche salarié ASP - Étape 4",
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

    employee_record = job_application.employee_record.full_fetch().latest("created_at")

    if request.method == "POST":
        back_url = f'{reverse("employee_record_views:list")}?status={employee_record.status}'
        employee_record.update_as_ready()
        toast_title, toast_message = (
            "La création de cette fiche salariée est terminée",
            "Vous pouvez suivre l'avancement de son traitement par l'ASP en sélectionnant les différents statuts.",
        )
        messages.success(
            request,
            f"{toast_title}||{toast_message}",
            extra_tags="toast",
        )
        return HttpResponseRedirect(back_url)

    context = {
        "employee_record": employee_record,
        "job_application": job_application,
        "steps": STEPS,
        "step": 5,
        "matomo_custom_title": "Nouvelle fiche salarié ASP - Étape 5",
    }

    return render(request, template_name, context)


@login_required
def summary(request, employee_record_id, template_name="employee_record/summary.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    employee_record = get_object_or_404(EmployeeRecord.objects.full_fetch(), pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    context = {
        "employee_record": employee_record,
        "matomo_custom_title": "Détail fiche salarié ASP",
    }

    return render(request, template_name, context)


@login_required
def disable(request, employee_record_id, template_name="employee_record/disable.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    employee_record = get_object_or_404(EmployeeRecord.objects.full_fetch(), pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    back_url = f'{reverse("employee_record_views:list")}?status={employee_record.status}'

    if not employee_record.can_be_disabled:
        messages.error(request, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE)
        return HttpResponseRedirect(back_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        employee_record.update_as_disabled()
        messages.success(request, "La fiche salarié a bien été désactivée.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "employee_record": employee_record,
        "matomo_custom_title": "Désactiver la fiche salarié ASP",
    }
    return render(request, template_name, context)


@login_required
def reactivate(request, employee_record_id, template_name="employee_record/reactivate.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    query_base = EmployeeRecord.objects.full_fetch()
    employee_record = get_object_or_404(query_base, pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    back_url = f'{reverse("employee_record_views:list")}?status={employee_record.status}'

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
        "matomo_custom_title": "Réactiver la fiche salarié ASP",
    }
    return render(request, template_name, context)
