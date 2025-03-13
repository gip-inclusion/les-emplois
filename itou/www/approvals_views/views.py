import logging
import pathlib
import urllib.parse
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.db.models import Max, Prefetch
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
    ProlongationRequest,
    ProlongationRequestDenyInformation,
    Suspension,
)
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.files.models import File
from itou.job_applications.enums import JobApplicationState
from itou.utils import constants as global_constants
from itou.utils.auth import check_user
from itou.utils.pagination import ItouPaginator, pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.approvals_views.forms import (
    ApprovalForm,
    ProlongationRequestDenyInformationProposedActionsForm,
    ProlongationRequestDenyInformationReasonExplanationForm,
    ProlongationRequestDenyInformationReasonForm,
    ProlongationRequestFilterForm,
    SuspensionEndDateForm,
    SuspensionForm,
    get_prolongation_form,
)


logger = logging.getLogger(__name__)


class ApprovalBaseViewMixin:
    model = Approval

    def __init__(self):
        super().__init__()
        self.siae = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.siae = get_current_company_or_404(request)

        if not self.siae.is_subject_to_eligibility_rules:
            raise PermissionDenied

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["siae"] = self.siae
        return context


class ApprovalListView(ApprovalBaseViewMixin, ListView):
    paginate_by = 10
    paginator_class = ItouPaginator

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.siae:
            self.form = ApprovalForm(self.siae.pk, self.request.GET or None)

    def get_template_names(self):
        return ["approvals/includes/list_results.html" if self.request.htmx else "approvals/list.html"]

    def get_queryset(self):
        form_filters = [self.form.get_approvals_qs_filter()]
        if self.form.is_valid():
            form_filters += self.form.get_qs_filters()
        return (
            super()
            .get_queryset()
            .filter(*form_filters)
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
        return context


class ApprovalDetailView(UserPassesTestMixin, DetailView):
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
        select_related = ("declared_by", "declared_by_siae", "validated_by")
        for prolongation in approval.prolongation_set.select_related("prescriber_organization", *select_related):
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
        is_employer_with_accepted_application = False
        if self.request.user.is_employer:
            if application_states := self.object.user.job_applications.filter(
                to_company=self.request.current_organization,
            ).values_list("state", flat=True):
                # The employer has received an application and can access the approval detail
                if any(state == JobApplicationState.ACCEPTED for state in application_states):
                    # The employer has even accepted an application: the action buttons are visible
                    is_employer_with_accepted_application = True
            elif not self.object.user.job_applications.prescriptions_of(
                self.request.user, self.request.current_organization
            ).exists():
                # No received or sent applications: no reason to access this page
                raise PermissionDenied
        elif self.request.user.is_prescriber:
            if not self.object.user.job_applications.prescriptions_of(
                self.request.user, self.request.current_organization
            ).exists():
                raise PermissionDenied
        elif self.request.user.is_job_seeker:
            if self.object.user != self.request.user:
                raise PermissionDenied
        else:
            # test_func should prevent this case from happening but let's be safe
            logger.exception("This should never happen")
            raise PermissionDenied

        context = super().get_context_data(**kwargs)
        approval = self.object

        context["is_employer_with_accepted_application"] = is_employer_with_accepted_application
        context["can_view_personal_information"] = self.request.user.can_view_personal_information(approval.user)
        context["matomo_custom_title"] = "Détail PASS IAE"
        context["approval_deletion_form_url"] = None
        context["back_url"] = get_safe_url(self.request, "back_url", fallback_url=reverse("dashboard:index"))
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
            and self.request.current_organization.is_subject_to_eligibility_rules
            and approval.can_be_prolonged
        )

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


def prolongation_back_url(request):
    return get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))


def declare_prolongation(request, approval_id, template_name="approvals/declare_prolongation.html"):
    """
    Declare a prolongation for the given approval.
    """

    siae = get_current_company_or_404(request)
    approval = get_object_or_404(Approval, pk=approval_id)

    if not siae.is_subject_to_eligibility_rules or not approval.can_be_prolonged:
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
                    filename = pathlib.Path(tmpfile_key).name
                    with default_storage.open(tmpfile_key) as prolongation_report:
                        prolongation_report_key = default_storage.save(
                            f"prolongation_report/{filename}", prolongation_report
                        )
                    default_storage.delete(tmpfile_key)
                    prolongation.report_file = File.objects.create(key=prolongation_report_key)
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
        if not self.siae.is_subject_to_eligibility_rules:
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
        "approval__user", "declared_by_siae", "validated_by"
    )

    form = ProlongationRequestFilterForm(data=request.GET)
    if form.is_valid() and form.cleaned_data["only_pending"]:
        queryset = queryset.filter(status=approvals_enums.ProlongationRequestStatus.PENDING)

    context = {
        "form": form,
        "pager": pager(queryset, request.GET.get("page"), items_per_page=20),
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@require_safe
@check_user(lambda user: user.is_prescriber)
def prolongation_request_report_file(request, prolongation_request_id):
    prolongation_request = get_object_or_404(
        ProlongationRequest,
        pk=prolongation_request_id,
        report_file__isnull=False,
    )
    if prolongation_request.prescriber_organization_id not in [org.pk for org in request.organizations]:
        raise Http404
    return HttpResponseRedirect(default_storage.url(prolongation_request.report_file_id))


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
            "back_url": add_url_params(reverse("approvals:prolongation_requests_list"), {"only_pending": "on"}),
        }


class ProlongationRequestShowView(ProlongationRequestViewMixin, TemplateView):
    template_name = "approvals/prolongation_requests/show.html"


class ProlongationRequestGrantView(ProlongationRequestViewMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            self.prolongation_request.grant(request.user)
        except IntegrityError:
            messages.error(request, "Erreur: veuillez contacter le support.", extra_tags="toast")
            logger.exception("Failed to accept approval prolongation request")
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
                add_url_params(
                    reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.id}),
                    {"back_url": back_url},
                )
            )

        if request.POST.get("action") == "update_enddate":
            return HttpResponseRedirect(
                add_url_params(
                    reverse("approvals:suspension_update_enddate", kwargs={"suspension_id": suspension.id}),
                    {"back_url": back_url},
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
        suspension.end_at = form.cleaned_data["first_day_back_to_work"] - timedelta(days=1)
        suspension.updated_by = request.user
        suspension.save()
        messages.success(request, "Modification de suspension effectuée.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "suspension": suspension,
        "secondary_url": add_url_params(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": suspension_id}),
            {"back_url": back_url},
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
        suspension.delete()
        messages.success(
            request,
            f"La suspension de {suspension.approval.user.get_full_name()} a bien été supprimée.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id}))

    context = {
        "suspension": suspension,
        "secondary_url": add_url_params(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": suspension_id}),
            {"back_url": back_url},
        ),
        "reset_url": back_url,
        "lost_days": (timezone.localdate() - suspension.start_at).days + 1,
    }
    return render(request, template_name, context)
