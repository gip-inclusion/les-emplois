import enum

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_safe

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.employee_record.constants import get_availability_date_for_kind
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.forms import JobSeekerProfileModelForm
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.employee_record import can_create_employee_record, siae_is_allowed
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.employee_record_views.enums import EmployeeRecordOrder, MissingEmployeeCase
from itou.www.employee_record_views.forms import (
    AddEmployeeRecordChooseApprovalForm,
    AddEmployeeRecordChooseEmployeeForm,
    EmployeeRecordFilterForm,
    FindEmployeeOrJobSeekerForm,
    NewEmployeeRecordStep2Form,
    NewEmployeeRecordStep3ForEITIForm,
    NewEmployeeRecordStep3Form,
    NewEmployeeRecordStep4,
    SelectEmployeeRecordStatusForm,
)
from itou.www.utils.wizard import WizardView


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


@check_user(lambda user: user.is_employer)
def start_add_wizard(request):
    return AddView.initialize_session_and_start(request, reset_url=get_safe_url(request, "reset_url"))


class AddViewStep(enum.StrEnum):
    CHOOSE_EMPLOYEE = "choose-employee"
    CHOOSE_APPROVAL = "choose-approval"


class AddView(UserPassesTestMixin, WizardView):
    url_name = "employee_record_views:add"
    expected_session_kind = "add-employee-record"
    steps_config = {
        AddViewStep.CHOOSE_EMPLOYEE: AddEmployeeRecordChooseEmployeeForm,
        AddViewStep.CHOOSE_APPROVAL: AddEmployeeRecordChooseApprovalForm,
    }
    template_name = "employee_record/add.html"

    def test_func(self):
        return self.company.can_use_employee_record

    def setup_wizard(self):
        self.company = get_current_company_or_404(self.request)

    def get_form_kwargs(self, step):
        hiring_of_the_company = JobApplication.objects.accepted().filter(to_company=self.company)
        if step == AddViewStep.CHOOSE_EMPLOYEE:
            employees = []
            # Add job seekers in order, whithout duplicates
            for job_app in hiring_of_the_company.eligible_as_employee_record(self.company).select_related(
                "job_seeker"
            ):
                if job_app.job_seeker not in employees:
                    employees.append(job_app.job_seeker)
            return {"employees": employees}
        elif step == AddViewStep.CHOOSE_APPROVAL:
            employee = User.objects.get(
                kind=UserKind.JOB_SEEKER,
                pk=self.wizard_session.get(AddViewStep.CHOOSE_EMPLOYEE)["employee"],
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

    def done(self, *args, **kwargs):
        session_data = self.wizard_session.as_dict()
        approval = Approval.objects.get(
            pk=session_data[AddViewStep.CHOOSE_APPROVAL]["approval"],
            user=session_data[AddViewStep.CHOOSE_EMPLOYEE]["employee"],
        )
        job_application = (
            JobApplication.objects.filter(to_company=self.company, approval=approval)
            .accepted()
            .with_accepted_at()
            .latest("accepted_at")
        )
        return reverse("employee_record_views:create", kwargs={"job_application_id": job_application.pk})


@check_user(lambda user: user.is_employer)
def missing_employee(request, template_name="employee_record/missing_employee.html"):
    siae = get_current_company_or_404(request)
    back_url = add_url_params(
        reverse("employee_record_views:add"),
        {"reset_url": get_safe_url(request, "back_url", fallback_url=reverse("employee_record_views:list"))},
    )

    if not siae.can_use_employee_record:
        raise PermissionDenied

    all_job_seekers = sorted(
        JobApplication.objects.filter(to_company=siae).get_unique_fk_objects("job_seeker"),
        key=lambda u: u.get_full_name(),
    )
    form = FindEmployeeOrJobSeekerForm(employees=all_job_seekers, data=request.POST or None)

    employee_or_job_seeker = None
    approvals_data = []
    case = None

    if request.method == "POST" and form.is_valid():
        employee_or_job_seeker = get_object_or_404(
            User.objects.filter(kind=UserKind.JOB_SEEKER, pk=form.cleaned_data["employee"])
        )
        back_url = reverse("employee_record_views:missing_employee")

        hiring_of_the_company = (
            JobApplication.objects.filter(to_company=siae, job_seeker=employee_or_job_seeker)
            .accepted()
            .with_accepted_at()
            .select_related("approval")
            .order_by("-accepted_at")
        )

        # Keep only the oldest accepted job application for each approval
        approval_to_job_app_mapping = {ja.approval: ja for ja in hiring_of_the_company if ja.approval}

        for approval, job_application in approval_to_job_app_mapping.items():
            employee_record = (
                EmployeeRecord.objects.for_asp_company(siae).filter(approval_number=approval.number).first()
            )
            if employee_record:
                if employee_record.job_application.to_company == siae:
                    approval_case = MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_SAME_COMPANY
                else:
                    approval_case = MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_OTHER_COMPANY
            else:
                approval_case = MissingEmployeeCase.NO_EMPLOYEE_RECORD
            approvals_data.append([approval, job_application, approval_case, employee_record])

        approvals_data = sorted(approvals_data, key=lambda a: a[0].end_at, reverse=True)

        if not hiring_of_the_company.exists():
            case = MissingEmployeeCase.NO_HIRING
        elif not approvals_data:
            case = MissingEmployeeCase.NO_APPROVAL

    context = {
        "back_url": back_url,
        "form": form,
        "employee_or_job_seeker": employee_or_job_seeker,
        "approvals_data": approvals_data,
        "case": case,
        "MissingEmployeeCase": MissingEmployeeCase,
    }
    return render(request, template_name, context)


@require_safe
def list_employee_records(request, template_name="employee_record/list.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    filters_form = EmployeeRecordFilterForm(
        User.objects.filter(
            pk__in=EmployeeRecord.objects.for_company(siae)
            .exclude(status=Status.ARCHIVED)
            .values("job_application__job_seeker")
        ),
        data=request.GET,
    )
    filters_form.full_clean()

    form = SelectEmployeeRecordStatusForm(data=request.GET)
    form.full_clean()  # We do not use is_valid to validate each field independently
    # Redirect if status is missing or empty and we are not searching by job seeker
    if not form.cleaned_data.get("status") and not any(filters_form.cleaned_data.values()):
        return HttpResponseRedirect(
            reverse("employee_record_views:list")
            + f"?status={Status.NEW}&status={Status.REJECTED}&order={form.cleaned_data['order']}"
        )
    order_by = EmployeeRecordOrder(form.cleaned_data.get("order") or EmployeeRecordOrder.HIRING_START_AT_DESC)

    # Construct badges
    employee_record_badges = {
        row["status"]: row["cnt"]
        for row in EmployeeRecord.objects.for_company(siae).values("status").annotate(cnt=Count("status"))
    }
    # Set count of each status for badge display
    status_badges = [
        (employee_record_badges.get(Status.NEW, 0), "bg-info"),
        (employee_record_badges.get(Status.READY, 0), "bg-emploi-lightest text-info"),
        (employee_record_badges.get(Status.SENT, 0), "bg-emploi-lightest text-info"),
        (employee_record_badges.get(Status.REJECTED, 0), "bg-warning"),
        (employee_record_badges.get(Status.PROCESSED, 0), "bg-emploi-lightest text-info"),
        (employee_record_badges.get(Status.DISABLED, 0), "bg-emploi-lightest text-info"),
    ]

    employee_record_order_by = {
        EmployeeRecordOrder.NAME_ASC: (
            "job_application__job_seeker__last_name",
            "job_application__job_seeker__first_name",
        ),
        EmployeeRecordOrder.NAME_DESC: (
            "-job_application__job_seeker__last_name",
            "-job_application__job_seeker__first_name",
        ),
        EmployeeRecordOrder.HIRING_START_AT_ASC: ("job_application__hiring_start_at",),
        EmployeeRecordOrder.HIRING_START_AT_DESC: ("-job_application__hiring_start_at",),
    }[order_by]
    data = EmployeeRecord.objects.full_fetch().for_company(siae).order_by(*employee_record_order_by)
    if statuses := form.cleaned_data.get("status"):
        data = data.filter(status__in=[Status(value) for value in statuses])
    if job_seeker_id := filters_form.cleaned_data.get("job_seeker"):
        data = data.filter(job_application__job_seeker=job_seeker_id)

    num_recently_missing_employee_records = len(
        set(
            JobApplication.objects.eligible_as_employee_record(siae)
            .filter(hiring_start_at__gte=timezone.localdate() - relativedelta(months=4))
            .values_list("job_seeker_id", flat=True)
        )
    )

    context = {
        "form": form,
        "filters_form": filters_form,
        "badges": status_badges,
        "navigation_pages": pager(data, request.GET.get("page"), items_per_page=10),
        "feature_availability_date": get_availability_date_for_kind(siae.kind),
        "ordered_by_label": order_by.label,
        "matomo_custom_title": "Fiches salarié ASP",
        "back_url": reverse("dashboard:index"),
        "num_rejected_employee_records": employee_record_badges.get(Status.REJECTED, 0),
        "num_recently_missing_employee_records": num_recently_missing_employee_records,
    }

    return render(request, "employee_record/includes/list_results.html" if request.htmx else template_name, context)


def create(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 1: Name and birth date / place / country of the jobseeker
    """
    job_application = can_create_employee_record(request, job_application_id)
    form = JobSeekerProfileModelForm(data=request.POST or None, instance=job_application.job_seeker)
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
        "back_url": get_safe_url(request, "back_url"),
    }

    return render(request, template_name, context)


def create_step_2(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 2: Details and address lookup / check of the employee
    """
    job_application = can_create_employee_record(request, job_application_id)
    job_seeker = job_application.job_seeker
    profile = job_seeker.jobseeker_profile
    address_filled = job_seeker.post_code and job_seeker.address_line_1
    query_param = f"?status={request.GET.get('status')}" if request.GET.get("status") else ""

    # Perform a geolocation of the user address if possible:
    # - success : prefill form with geolocated data
    # - failure : display actual address and let user fill the form
    # This need to be done before passing the instance to the form otherwise fields will be shown empty
    if not profile.hexa_address_filled and address_filled:
        try:
            # Attempt to create a job seeker profile with an address prefilled
            profile.update_hexa_address()
        except ValidationError:
            # Not a big deal anymore, let user fill address form
            profile.clear_hexa_address()

    # At this point, a job seeker profile was created
    form = NewEmployeeRecordStep2Form(data=request.POST or None, instance=profile)
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

    if request.current_organization.kind == CompanyKind.EITI:
        form_class = NewEmployeeRecordStep3ForEITIForm
    else:
        form_class = NewEmployeeRecordStep3Form
    form = form_class(data=request.POST or None, instance=profile)

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


def create_step_5(request, job_application_id, template_name="employee_record/create.html"):
    """
    Create a new employee record from a given job application

    Step 5: Summary and validation
    """
    job_application = can_create_employee_record(request, job_application_id)

    if not job_application.job_seeker.has_jobseeker_profile:
        raise PermissionDenied

    employee_record = job_application.employee_record.full_fetch().latest("created_at")

    if request.method == "POST" and not job_application.hiring_starts_in_future:
        back_url = f"{reverse('employee_record_views:list')}?status={employee_record.status}"
        employee_record.ready(user=request.user)
        toast_title, toast_message = (
            "La création de cette fiche salarié est terminée",
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
        "back_url": get_safe_url(request, "back_url", fallback_url=reverse_lazy("employee_record_views:list")),
    }

    return render(request, template_name, context)


def disable(request, employee_record_id, template_name="employee_record/disable.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    employee_record = get_object_or_404(EmployeeRecord.objects.full_fetch(), pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    back_url = f"{reverse('employee_record_views:list')}?status={employee_record.status}"

    if not employee_record.disable.is_available():
        messages.error(request, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE)
        return HttpResponseRedirect(back_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        employee_record.disable(user=request.user)
        messages.success(request, "La fiche salarié a bien été désactivée.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "employee_record": employee_record,
        "matomo_custom_title": "Désactiver la fiche salarié ASP",
    }
    return render(request, template_name, context)


def reactivate(request, employee_record_id, template_name="employee_record/reactivate.html"):
    siae = get_current_company_or_404(request)

    if not siae.can_use_employee_record:
        raise PermissionDenied

    query_base = EmployeeRecord.objects.full_fetch()
    employee_record = get_object_or_404(query_base, pk=employee_record_id)
    job_application = employee_record.job_application

    if not siae_is_allowed(job_application, siae):
        raise PermissionDenied

    back_url = f"{reverse('employee_record_views:list')}?status={employee_record.status}"

    if employee_record.status != Status.DISABLED:
        messages.error(request, EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE)
        return HttpResponseRedirect(back_url)

    if request.method == "POST" and request.POST.get("confirm") == "true":
        try:
            employee_record.enable(user=request.user)
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
