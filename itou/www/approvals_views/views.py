import enum
import logging
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db.models import F, Max, OuterRef, Prefetch, Subquery
from django.db.models.base import Coalesce
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_safe
from django.views.generic import DetailView, ListView, TemplateView
from formtools.wizard.views import NamedUrlSessionWizardView

from itou.approvals import enums as approvals_enums
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.models import (
    SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE,
    Approval,
    Prolongation,
    ProlongationRequest,
    ProlongationRequestDenyInformation,
    Suspension,
)
from itou.approvals.perms import PERMS_READ_AND_WRITE, can_view_approval_details
from itou.companies.models import Contract
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.files.models import save_file
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils import constants as global_constants
from itou.utils.auth import check_user
from itou.utils.db import (
    ExclusionViolationError,
    UniqueViolationError,
    maybe_exclusion_violation,
    maybe_unique_violation,
)
from itou.utils.pagination import ItouPaginator, pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX
from itou.utils.urls import get_safe_url
from itou.www.approvals_views.forms import (
    ApprovalForm,
    ContractStatus,
    ProlongationRequestDenyInformationProposedActionsForm,
    ProlongationRequestDenyInformationReasonExplanationForm,
    ProlongationRequestDenyInformationReasonForm,
    ProlongationRequestFilterForm,
    SuspensionEndDateForm,
    SuspensionForm,
    get_prolongation_form,
)


logger = logging.getLogger(__name__)


def _add_contract_data(queryset, siae):
    """
    The contract data (their end dates) is used to filter out job seekers that have not been assisted by a company
    for a while.
    We don't have a clear link between the approval and a contract, so we consider the contracts that overlap with
    the approval dates (ie. exclude contracts that started and ended before the approval start date, or that started
    and ended after the approval end date)
    If no contract is found (eg. when a company just hired a job seeker, the contract is not immediately available)
    use the accepted job application's `hiring_end_at`. If it has been left unfilled, use the approval's end date.
    """
    contracts_qs = (
        Contract.objects.filter(job_seeker=OuterRef("user"), company=siae)
        .annotate(end_date_or_today=Coalesce("end_date", timezone.localdate()))
        .exclude(end_date_or_today__lt=OuterRef("start_at"))
        .exclude(start_date__gt=OuterRef("end_at"))
    )
    job_applications_qs = JobApplication.objects.filter(
        state=JobApplicationState.ACCEPTED, to_company=siae, approval=OuterRef("pk")
    )

    return queryset.annotate(
        contract_end_at=Coalesce(
            Subquery(contracts_qs.order_by("-end_date_or_today").values("end_date_or_today")[:1]),
            Subquery(job_applications_qs.order_by("-hiring_end_at").values("hiring_end_at")[:1]),
            F("end_at"),
        )
    )


class ApprovalDisplayKind(enum.StrEnum):
    LIST = "list"
    TABLE = "table"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)

    # Ease the use in templates by avoiding the need to have access to JobApplicationsDisplayKind
    def is_list(self):
        return self is self.LIST

    def is_table(self):
        return self is self.TABLE


class ApprovalBaseViewMixin:
    model = Approval

    def __init__(self):
        super().__init__()
        self.siae = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.siae = get_current_company_or_404(request)

        if not self.siae.is_subject_to_iae_rules:
            raise PermissionDenied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["siae"] = self.siae
        return context


class ApprovalListView(ApprovalBaseViewMixin, ListView):
    paginate_by = settings.PAGE_SIZE_DEFAULT
    paginator_class = ItouPaginator

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.siae:
            self.form = ApprovalForm(self.siae.pk, self.request.GET)

        try:
            self.display_kind = ApprovalDisplayKind(request.GET.get("display"))
        except ValueError:
            self.display_kind = ApprovalDisplayKind.TABLE

    def get_template_names(self):
        return ["approvals/includes/list_results.html" if self.request.htmx else "approvals/list.html"]

    def get_queryset(self):
        form_filters = [self.form.get_approvals_qs_filter()]
        if self.form.is_valid():
            form_filters += self.form.get_qs_filters()

        queryset = super().get_queryset()
        if self.form.cleaned_data.get("contract_status", ContractStatus.ALL) != ContractStatus.ALL:
            queryset = _add_contract_data(queryset, self.siae)
        return (
            queryset.filter(*form_filters)
            .distinct()  # Because of the suspended_qs_filter that looks into suspensions
            .select_related("user")
            .prefetch_related("suspension_set")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters_form"] = self.form
        context["filters_counter"] = self.form.get_filters_counter()
        context["back_url"] = reverse("dashboard:index")
        context["num_rejected_employee_records"] = (
            EmployeeRecord.objects.for_company(self.siae).filter(status=Status.REJECTED).count()
        )
        context["mon_recap_banner_departments"] = settings.MON_RECAP_BANNER_DEPARTMENTS
        context["display_kind"] = self.display_kind
        return context


class BaseApprovalDetailView(UserPassesTestMixin, DetailView):
    model = Approval
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    active_tab = None

    def can_view_contracts(self):
        return self.request.from_authorized_prescriber or self.request.user.is_employer

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        approval = self.object
        # Display the action buttons if the employer has accepted an application
        permissions = can_view_approval_details(self.request, approval)
        if not permissions:
            raise PermissionDenied
        context["active_tab"] = self.active_tab
        context["can_view_contracts"] = self.can_view_contracts()
        context["is_employer_with_accepted_application"] = permissions == PERMS_READ_AND_WRITE
        context["can_view_personal_information"] = can_view_personal_information(self.request, approval.user)
        context["matomo_custom_title"] = "Détail PASS IAE"
        context["back_url"] = get_safe_url(self.request, "back_url", fallback_url=reverse("dashboard:index"))

        # Display or not the deletion form link
        context["approval_deletion_form_url"] = None
        if self.request.user.is_employer and approval.is_in_progress:
            approval_can_be_deleted = False

            long_suspensions = [
                suspension
                for suspension in approval.suspension_set.all()
                if (timezone.localdate() - suspension.start_at if suspension.is_in_progress else suspension.duration)
                > SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE
            ]

            if any(suspension.is_in_progress for suspension in long_suspensions):
                approval_can_be_deleted = True
            elif long_suspensions:
                last_hiring_start_at = approval.jobapplication_set.accepted().aggregate(Max("hiring_start_at"))[
                    "hiring_start_at__max"
                ]
                if last_hiring_start_at is None or any(
                    suspension.end_at > last_hiring_start_at for suspension in long_suspensions
                ):
                    approval_can_be_deleted = True

            if approval_can_be_deleted:
                # ... and no hiring after this suspension: this approval is eligible for deletion
                context["approval_deletion_form_url"] = "https://tally.so/r/3je84Q?" + urllib.parse.urlencode(
                    {
                        "siaeID": self.request.current_organization.pk,
                        "nomSIAE": self.request.current_organization.display_name,
                        "prenomemployeur": self.request.user.first_name,
                        "nomemployeur": self.request.user.last_name,
                        "emailemployeur": self.request.user.email,
                        "userID": self.request.user.pk,
                        "numPASS": approval.number_with_spaces,
                        "prenomsalarie": approval.user.first_name,
                        "nomsalarie": approval.user.last_name,
                    }
                )

        return context


class ApprovalDetailView(BaseApprovalDetailView):
    model = Approval
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    queryset = Approval.objects.select_related("user__jobseeker_profile").prefetch_related(
        # Useful for get_suspensions method and the approval remainder field
        Prefetch(
            "suspension_set",
            queryset=Suspension.objects.select_related("siae"),
        ),
    )
    template_name = "approvals/details.html"
    active_tab = "details"

    def test_func(self):
        # More checks are performed in get_context_data method
        return self.request.user.is_prescriber or self.request.user.is_employer or self.request.user.is_job_seeker

    def get_prolongation_and_requests(self, approval):
        def _format_for_template(user, org):
            parts = []
            if user:
                parts.append(user.get_full_name())
            if org:
                parts.append(org.display_name)
            return " - ".join(parts)

        prolongations = []
        select_related = ("declared_by", "declared_by_siae")
        for prolongation in approval.prolongation_set.select_related(
            "prescriber_organization", "validated_by", *select_related
        ):
            prolongation.declared_by_for_template = _format_for_template(
                prolongation.declared_by, prolongation.declared_by_siae
            )
            prolongation.validated_by_for_template = _format_for_template(
                prolongation.validated_by, prolongation.prescriber_organization
            )
            prolongations.append(prolongation)

        for prolongation_request in approval.prolongationrequest_set.select_related(*select_related).filter(
            prolongation__isnull=True
        ):
            prolongation_request.declared_by_for_template = _format_for_template(
                prolongation_request.declared_by, prolongation_request.declared_by_siae
            )
            prolongation_request.validated_by_for_template = None  # Not validated yet
            prolongations.append(prolongation_request)
        return sorted(prolongations, key=lambda p: p.start_at, reverse=True)

    def get_suspensions(self, approval):
        suspensions = sorted(approval.suspension_set.all(), key=lambda s: s.start_at, reverse=True)
        for suspension in suspensions:
            if self.request.user.is_employer:
                suspension.can_be_handled_by_current_user = suspension.can_be_handled_by_siae(
                    self.request.current_organization
                )
            else:
                suspension.can_be_handled_by_current_user = False
        return suspensions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        approval = self.object

        context["suspensions"] = self.get_suspensions(approval)
        context["prolongations"] = self.get_prolongation_and_requests(approval)
        context["prolongation_request_pending"] = any(
            getattr(prolongation, "status", None) == approvals_enums.ProlongationRequestStatus.PENDING
            for prolongation in context["prolongations"]
        )
        context["can_be_suspended_by_current_user"] = (
            self.request.user.is_employer and approval.can_be_suspended_by_siae(self.request.current_organization)
        )
        context["can_be_prolonged_by_current_user"] = (
            self.request.user.is_employer
            and self.request.current_organization.is_subject_to_iae_rules
            and approval.can_be_prolonged
        )

        return context


class ApprovalPrintableDisplay(ApprovalBaseViewMixin, TemplateView):
    template_name = "approvals/printable_approval.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        queryset = Approval.objects.select_related("user")
        approval = get_object_or_404(queryset, public_id=self.kwargs["public_id"])

        diagnosis = approval.eligibility_diagnosis
        diagnosis_author = None
        diagnosis_author_org = None
        diagnosis_author_org_name = None

        if diagnosis:
            diagnosis_author = diagnosis.author.get_full_name()
            diagnosis_author_org = diagnosis.author_prescriber_organization or diagnosis.author_siae
            if diagnosis_author_org:
                diagnosis_author_org_name = diagnosis_author_org.display_name

        context.update(
            {
                "approval": approval,
                "itou_help_center_url": global_constants.ITOU_HELP_CENTER_URL,
                "diagnosis_author": diagnosis_author,
                "diagnosis_author_org_name": diagnosis_author_org_name,
                "matomo_custom_title": "Attestation de délivrance d'agrément",
            }
        )
        return context


class ContractsView(BaseApprovalDetailView):
    queryset = Approval.objects
    template_name = "approvals/contracts.html"
    active_tab = "contracts"

    def test_func(self):
        return self.can_view_contracts()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["contracts"] = (
            Contract.objects.filter(job_seeker=self.object.user)
            # Filter out contracts that do not overlap the approval
            .exclude(end_date__lt=self.object.start_at)
            .exclude(start_date__gt=self.object.end_at)
            .select_related("company")
            .order_by("-start_date")
        )
        return context


def prolongation_back_url(request):
    return get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))


def declare_prolongation(request, approval_id, template_name="approvals/declare_prolongation.html"):
    """
    Declare a prolongation for the given approval.
    """

    siae = get_current_company_or_404(request)
    approval = get_object_or_404(Approval, pk=approval_id)

    if not siae.is_subject_to_iae_rules or not approval.can_be_prolonged:
        raise PermissionDenied()

    back_url = prolongation_back_url(request)
    preview = False

    form = get_prolongation_form(
        approval=approval,
        siae=siae,
        data=request.POST or None,
        files=request.FILES or None,
        back_url=back_url,
    )

    # The file was saved before the preview step, and its reference is stored in the session.
    # Don’t validate it.
    if request.POST.get("save"):
        try:
            del form.fields["report_file"]
        except KeyError:
            pass

    if request.method == "POST" and form.is_valid():
        prolongation = form.save(commit=False)
        prolongation.created_by = request.user
        prolongation.declared_by = request.user
        session_key = f"declare_prolongation:{siae.pk}:{approval.pk}"

        if request.POST.get("preview"):
            preview = True
            # The file cannot be re-submitted and is stored for the duration of the preview.
            try:
                prolongation_report = form.cleaned_data["report_file"]
            except KeyError:
                pass
            else:
                request.session[session_key] = default_storage.save(
                    f"{TEMPORARY_STORAGE_PREFIX}/{prolongation_report.name}", prolongation_report
                )
        elif request.POST.get("save"):
            if siae.can_upload_prolongation_report:
                try:
                    tmpfile_key = request.session.pop(session_key)
                except KeyError:
                    pass
                else:
                    with default_storage.open(tmpfile_key) as prolongation_report:
                        file = save_file(folder="prolongation_report/", file=prolongation_report)
                    prolongation.report_file = file
                    default_storage.delete(tmpfile_key)
            prolongation.save()
            prolongation.notify_authorized_prescriber()
            messages.success(request, "Déclaration de prolongation enregistrée.", extra_tags="toast")
            return HttpResponseRedirect(back_url)

    context = {
        "approval": approval,
        "back_url": back_url,
        "form": form,
        "preview": preview,
        "unfold_details": form.data.get("reason") in PROLONGATION_REPORT_FILE_REASONS,
        "can_upload_prolongation_report": siae.can_upload_prolongation_report,
    }

    return render(request, template_name, context)


class DeclareProlongationHTMXFragmentView(TemplateView):
    """
    HTMX interactions on dynamic parts of the prolongation declaration form
    """

    # Select form errors to be cleared
    clear_errors = []

    def _clear_errors(self):
        # Clear given form errors if validation is not needed (but triggered)
        for error_key in self.clear_errors:
            self.form.errors.pop(error_key, None)

    def setup(self, request, approval_id, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.siae = get_current_company_or_404(request)
        if not self.siae.is_subject_to_iae_rules:
            raise PermissionDenied()
        self.approval = get_object_or_404(Approval, pk=approval_id)

        if not self.approval.can_be_prolonged:
            raise PermissionDenied()

        self.form = get_prolongation_form(
            approval=self.approval,
            siae=self.siae,
            data=request.POST or None,
            files=request.FILES or None,
            back_url=prolongation_back_url(request),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context |= {
            "approval": self.approval,
            "form": self.form,
        }
        return context

    def post(self, request, *args, **kwargs):
        try:
            self.form.is_valid()
        except TypeError:
            # django-bootstrap4 does a validation of form when rendering template by calling 'form.errors':
            # - the first logical action on the form does an HTMX reload, and a partial rendering
            # - thus triggering a 'fullclean()' on a yet incomplete form 'Prolongation' instance,
            # - even if *not* asked to do so (form has not yet been explicitly validated)
            # - leading to a TypeError (date validation processing in 'Prolongation.clean()')
            #
            # If anybody knows how to disable this behavior of bootstrap4 (if possible)...
            pass
        self._clear_errors()

        return render(request, self.template_name, self.get_context_data())


class UpdateFormForReasonView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/prolongation_declaration_form.html"
    clear_errors = ("email", "end_at", "report_file")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context |= {
            "back_url": prolongation_back_url(self.request),
            "unfold_details": self.form.data.get("reason") in PROLONGATION_REPORT_FILE_REASONS,
            "can_upload_prolongation_report": self.siae.can_upload_prolongation_report,
        }
        return context


class CheckPrescriberEmailView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/declaration_prescriber_email.html"
    clear_errors = ("prescriber_organization",)


class CheckContactDetailsView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/declaration_contact_details.html"
    clear_errors = ("contact_email", "contact_phone")


def prolongation_requests_list(request, template_name="approvals/prolongation_requests/list.html"):
    current_organization = get_current_org_or_404(request)
    if not current_organization.is_authorized:
        raise Http404()

    queryset = ProlongationRequest.objects.filter(prescriber_organization=current_organization).select_related(
        "approval__user", "declared_by_siae", "assigned_to"
    )

    form = ProlongationRequestFilterForm(data=request.GET)
    if form.is_valid() and form.cleaned_data["only_pending"]:
        queryset = queryset.filter(status=approvals_enums.ProlongationRequestStatus.PENDING)

    context = {
        "form": form,
        "pager": pager(queryset, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_DEFAULT),
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_prescriber)
def prolongation_request_report_file(request, prolongation_request_id):
    prolongation_request = get_object_or_404(
        ProlongationRequest.objects.select_related("report_file"),
        pk=prolongation_request_id,
        report_file__isnull=False,
    )
    if prolongation_request.prescriber_organization_id not in [org.pk for org in request.organizations]:
        raise Http404
    return HttpResponseRedirect(prolongation_request.report_file.url())


class ProlongationRequestViewMixin:
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.prolongation_request = get_object_or_404(
            ProlongationRequest.objects.filter(prescriber_organization=get_current_org_or_404(request)).select_related(
                "approval__user",
                "deny_information",
            ),
            pk=kwargs["prolongation_request_id"],
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "prolongation_request": self.prolongation_request,
            "matomo_custom_title": "Demande de prolongation",
            "back_url": reverse("approvals:prolongation_requests_list", query={"only_pending": "on"}),
        }


class ProlongationRequestShowView(ProlongationRequestViewMixin, TemplateView):
    template_name = "approvals/prolongation_requests/show.html"


class ProlongationRequestGrantView(ProlongationRequestViewMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        if self.prolongation_request.status == approvals_enums.ProlongationRequestStatus.GRANTED:
            messages.success(
                request,
                f"La prolongation de {self.prolongation_request.approval.user.get_full_name()} a déjà été acceptée.",
                extra_tags="toast",
            )
            return HttpResponseRedirect(reverse("approvals:prolongation_requests_list"))

        try:
            with (
                maybe_exclusion_violation(Prolongation, "exclude_prolongation_overlapping_dates"),
                maybe_unique_violation(Prolongation, "approvals_prolongation_request_id_key"),
            ):
                self.prolongation_request.grant(request.user)
        except (ExclusionViolationError, UniqueViolationError) as e:
            messages.error(request, str(e), extra_tags="toast")
            return HttpResponseRedirect(
                reverse(
                    "approvals:prolongation_request_show",
                    kwargs={"prolongation_request_id": self.prolongation_request.pk},
                )
            )

        messages.success(
            request,
            f"La prolongation de {self.prolongation_request.approval.user.get_full_name()} a bien été acceptée.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(reverse("approvals:prolongation_requests_list"))


def _show_proposed_actions_form(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step("reason") or {}
    return cleaned_data.get("reason") == approvals_enums.ProlongationRequestDenyReason.IAE


class ProlongationRequestDenyView(ProlongationRequestViewMixin, NamedUrlSessionWizardView):
    template_name = "approvals/prolongation_requests/deny.html"
    form_list = [
        ("reason", ProlongationRequestDenyInformationReasonForm),
        ("reason_explanation", ProlongationRequestDenyInformationReasonExplanationForm),
        ("proposed_actions", ProlongationRequestDenyInformationProposedActionsForm),
    ]
    condition_dict = {
        "proposed_actions": _show_proposed_actions_form,
    }

    def get_form_kwargs(self, step=None):
        if step == "reason":
            return {"employee": self.prolongation_request.approval.user}
        return {}

    def done(self, form_list, *args, **kwargs):
        self.prolongation_request.deny(
            self.request.user,
            ProlongationRequestDenyInformation(**self.get_all_cleaned_data()),
        )
        messages.success(
            self.request,
            f"La prolongation de {self.prolongation_request.approval.user.get_full_name()} a bien été refusée.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(reverse("approvals:prolongation_requests_list"))

    def get_step_url(self, step):
        return reverse(self.url_name, kwargs={"prolongation_request_id": self.prolongation_request.pk, "step": step})


def suspend(request, approval_id, template_name="approvals/suspend.html"):
    siae = get_current_company_or_404(request)
    approval = get_object_or_404(Approval, pk=approval_id)

    if not approval.can_be_suspended_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    preview = False

    form = SuspensionForm(approval=approval, siae=siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        suspension = form.save(commit=False)
        suspension.created_by = request.user

        if request.POST.get("edit"):
            preview = False
        if request.POST.get("preview"):
            preview = True
        elif request.POST.get("save"):
            suspension.save()
            messages.success(request, "Suspension effectuée.", extra_tags="toast")
            logger.info(
                "user=%s created suspension=%s (approval=%s) from %s to %s",
                request.user.pk,
                suspension.pk,
                approval.pk,
                suspension.start_at,
                suspension.end_at,
            )
            return HttpResponseRedirect(back_url)

    context = {
        "approval": approval,
        "back_url": back_url,
        "form": form,
        "preview": preview,
    }
    return render(request, template_name, context)


def suspension_action_choice(request, suspension_id, template_name="approvals/suspension_action_choice.html"):
    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(
        Suspension.objects.select_related("approval__user").prefetch_related("approval__suspension_set"),
        pk=suspension_id,
    )

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id}),
    )

    if request.method == "POST":
        if request.POST.get("action") == "delete":
            return HttpResponseRedirect(
                reverse(
                    "approvals:suspension_delete",
                    kwargs={"suspension_id": suspension.id},
                    query={"back_url": back_url},
                )
            )

        if request.POST.get("action") == "update_enddate":
            return HttpResponseRedirect(
                reverse(
                    "approvals:suspension_update_enddate",
                    kwargs={"suspension_id": suspension.id},
                    query={"back_url": back_url},
                )
            )

        return HttpResponseBadRequest('invalid "action" parameter')

    context = {
        "suspension": suspension,
        "back_url": back_url,
    }
    return render(request, template_name, context)


def suspension_update(request, suspension_id, template_name="approvals/suspension_update.html"):
    """
    Edit the given suspension.
    """

    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(
        Suspension.objects.select_related("approval__user").prefetch_related("approval__suspension_set"),
        pk=suspension_id,
    )

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    form = SuspensionForm(
        approval=suspension.approval,
        siae=siae,
        instance=suspension,
        data=request.POST or None,
    )

    if request.method == "POST" and form.is_valid():
        suspension = form.save(commit=False)
        suspension.updated_by = request.user
        suspension.save()
        logger.info(
            "user=%s updated suspension=%s (approval=%s) dates from %s to %s",
            request.user.pk,
            suspension.pk,
            suspension.approval.pk,
            [str(form.initial["start_at"]), str(form.initial["end_at"])],
            [str(form.cleaned_data["start_at"]), str(form.cleaned_data["end_at"])],
        )
        messages.success(request, "Modification de suspension effectuée.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "suspension": suspension,
        "back_url": back_url,
        "form": form,
    }
    return render(request, template_name, context)


def suspension_update_enddate(request, suspension_id, template_name="approvals/suspension_update_enddate.html"):
    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(
        Suspension.objects.select_related("approval__user").prefetch_related("approval__suspension_set"),
        pk=suspension_id,
    )

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    form = SuspensionEndDateForm(
        approval=suspension.approval,
        siae=siae,
        instance=suspension,
        data=request.POST or None,
    )

    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id}),
    )

    if request.method == "POST" and form.is_valid():
        previous_end_at = suspension.end_at
        suspension.end_at = form.cleaned_data["first_day_back_to_work"] - timedelta(days=1)
        suspension.updated_by = request.user
        suspension.save()
        logger.info(
            "user=%s updated suspension=%s (approval=%s) end date from %s to %s",
            request.user.pk,
            suspension.pk,
            suspension.approval.pk,
            previous_end_at,
            suspension.end_at,
        )
        messages.success(request, "Modification de suspension effectuée.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "suspension": suspension,
        "secondary_url": reverse(
            "approvals:suspension_action_choice",
            kwargs={"suspension_id": suspension_id},
            query={"back_url": back_url},
        ),
        "reset_url": back_url,
        "form": form,
    }
    return render(request, template_name, context)


def suspension_delete(request, suspension_id, template_name="approvals/suspension_delete.html"):
    """
    Delete the given suspension.
    """

    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(
        Suspension.objects.select_related("approval__user").prefetch_related("approval__suspension_set"),
        pk=suspension_id,
    )

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id}),
    )

    if request.method == "POST" and request.POST.get("confirm") == "true":
        old_pk = suspension.pk
        suspension.delete()
        logger.info(
            "user=%s deleted suspension=%s (approval=%s) which ranged from %s to %s",
            request.user.pk,
            old_pk,
            suspension.approval.pk,
            suspension.start_at,
            suspension.end_at,
        )
        messages.success(
            request,
            f"La suspension de {suspension.approval.user.get_full_name()} a bien été supprimée.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id}))

    context = {
        "suspension": suspension,
        "secondary_url": reverse(
            "approvals:suspension_action_choice",
            kwargs={"suspension_id": suspension_id},
            query={"back_url": back_url},
        ),
        "reset_url": back_url,
        "lost_days": (timezone.localdate() - suspension.start_at).days + 1,
    }
    return render(request, template_name, context)
