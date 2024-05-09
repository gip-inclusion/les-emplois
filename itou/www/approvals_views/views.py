import logging
import pathlib
import urllib.parse
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.db.models import Prefetch
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_safe
from django.views.generic import DetailView, ListView, TemplateView
from formtools.wizard.views import NamedUrlSessionWizardView

from itou.approvals import enums as approvals_enums
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.models import (
    Approval,
    PoleEmploiApproval,
    ProlongationRequest,
    ProlongationRequestDenyInformation,
    Suspension,
)
from itou.approvals.utils import get_user_last_accepted_siae_job_application
from itou.files.models import File
from itou.job_applications.enums import JobApplicationState, Origin, SenderKind
from itou.job_applications.models import JobApplication
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.pagination import ItouPaginator, pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.apply.forms import JobSeekerExistsForm
from itou.www.approvals_views.forms import (
    ApprovalForm,
    PoleEmploiApprovalSearchForm,
    ProlongationRequestDenyInformationProposedActionsForm,
    ProlongationRequestDenyInformationReasonExplanationForm,
    ProlongationRequestDenyInformationReasonForm,
    ProlongationRequestFilterForm,
    SuspensionEndDateForm,
    SuspensionForm,
    get_prolongation_form,
)


logger = logging.getLogger(__name__)


SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE = timedelta(days=365)


class ApprovalBaseViewMixin(LoginRequiredMixin):
    model = Approval

    def __init__(self):
        super().__init__()
        self.siae = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if request.user.is_authenticated:
            self.siae = get_current_company_or_404(request)

            if not self.siae.is_subject_to_eligibility_rules:
                return self.handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["siae"] = self.siae
        return context

    def get_job_application(self, approval):
        return (
            JobApplication.objects.filter(
                job_seeker=approval.user,
                state=JobApplicationState.ACCEPTED,
                to_company=self.siae,
                approval=approval,
            )
            .select_related(
                "eligibility_diagnosis",
                "eligibility_diagnosis__author_siae",
                "eligibility_diagnosis__author_prescriber_organization",
                "eligibility_diagnosis__job_seeker",
                "sender_prescriber_organization",
            )
            .first()
        )


class ApprovalDetailView(ApprovalBaseViewMixin, DetailView):
    model = Approval
    queryset = Approval.objects.select_related("user__jobseeker_profile").prefetch_related(
        "suspension_set",
        Prefetch(
            "prolongationrequest_set",
            queryset=ProlongationRequest.objects.select_related(
                "declared_by", "validated_by", "processed_by", "prescriber_organization"
            ),
        ),
    )
    template_name = "approvals/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        approval = self.object
        job_application = self.get_job_application(self.object)

        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["can_edit_personal_information"] = self.request.user.can_edit_personal_information(approval.user)
        context["approval_can_be_suspended_by_siae"] = approval.can_be_suspended_by_siae(self.siae)
        context["approval_can_be_prolonged"] = approval.can_be_prolonged
        context["job_application"] = job_application
        context["hiring_pending"] = job_application and job_application.is_pending
        context["matomo_custom_title"] = "Profil salarié"
        context["eligibility_diagnosis"] = job_application and job_application.get_eligibility_diagnosis(
            self.request.user
        )
        context["approval_deletion_form_url"] = None
        context["back_url"] = get_safe_url(self.request, "back_url", fallback_url=reverse_lazy("approvals:list"))

        if approval.is_in_progress:
            for suspension in approval.suspensions_by_start_date_asc:
                if suspension.is_in_progress:
                    suspension_duration = date.today() - suspension.start_at
                    has_hirings_after_suspension = False
                else:
                    suspension_duration = suspension.duration
                    has_hirings_after_suspension = (
                        approval.jobapplication_set.accepted().filter(hiring_start_at__gte=suspension.end_at).exists()
                    )

                if (
                    suspension_duration > SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE
                    and not has_hirings_after_suspension
                ):
                    context["approval_deletion_form_url"] = "https://tally.so/r/3je84Q?" + urllib.parse.urlencode(
                        {
                            "siaeID": self.siae.pk,
                            "nomSIAE": self.siae.display_name,
                            "prenomemployeur": self.request.user.first_name,
                            "nomemployeur": self.request.user.last_name,
                            "emailemployeur": self.request.user.email,
                            "userID": self.request.user.pk,
                            "numPASS": approval.number_with_spaces,
                            "prenomsalarie": approval.user.first_name,
                            "nomsalarie": approval.user.last_name,
                        }
                    )
                    break

        context["all_job_applications"] = (
            JobApplication.objects.filter(
                job_seeker=approval.user,
                to_company=self.siae,
            )
            .select_related("sender", "to_company")
            .prefetch_related("selected_jobs")
        )
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
        return context


class ApprovalPrintableDisplay(ApprovalBaseViewMixin, TemplateView):
    template_name = "approvals/printable_approval.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        queryset = Approval.objects.select_related("user")
        approval = get_object_or_404(queryset, pk=self.kwargs["approval_id"])

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


@login_required
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

        if request.user.is_authenticated:
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


@login_required
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
        "pager": pager(queryset, request.GET.get("page"), items_per_page=10),
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@require_safe
@login_required
def prolongation_request_report_file(request, prolongation_request_id):
    prolongation_request = get_object_or_404(
        ProlongationRequest,
        pk=prolongation_request_id,
        report_file__isnull=False,
    )
    if prolongation_request.prescriber_organization_id not in [org.pk for org in request.organizations]:
        raise Http404
    return HttpResponseRedirect(default_storage.url(prolongation_request.report_file_id))


class ProlongationRequestViewMixin(LoginRequiredMixin):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.prolongation_request = get_object_or_404(
                ProlongationRequest.objects.filter(
                    prescriber_organization=get_current_org_or_404(request)
                ).select_related(
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


@login_required
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


@login_required()
def suspension_action_choice(request, suspension_id, template_name="approvals/suspension_action_choice.html"):
    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(Suspension.objects.select_related("approval__user"), pk=suspension_id)

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    if request.method == "POST":
        if request.POST.get("action") == "delete":
            return HttpResponseRedirect(
                reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.id})
            )

        if request.POST.get("action") == "update_enddate":
            return HttpResponseRedirect(
                reverse("approvals:suspension_update_enddate", kwargs={"suspension_id": suspension.id})
            )

        return HttpResponseBadRequest('invalid "action" parameter')

    back_url = get_safe_url(
        request, "back_url", fallback_url=reverse("approvals:detail", kwargs={"pk": suspension.approval_id})
    )
    context = {
        "suspension": suspension,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def suspension_update(request, suspension_id, template_name="approvals/suspension_update.html"):
    """
    Edit the given suspension.
    """

    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(Suspension.objects.select_related("approval__user"), pk=suspension_id)

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


@login_required()
def suspension_update_enddate(request, suspension_id, template_name="approvals/suspension_update_enddate.html"):
    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(Suspension.objects.select_related("approval__user"), pk=suspension_id)

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
        fallback_url=reverse("approvals:suspension_action_choice", kwargs={"suspension_id": suspension_id}),
    )

    if request.method == "POST" and form.is_valid():
        suspension.end_at = form.cleaned_data["first_day_back_to_work"] - timedelta(days=1)
        suspension.updated_by = request.user
        suspension.save()
        messages.success(request, "Modification de suspension effectuée.", extra_tags="toast")
        return HttpResponseRedirect(reverse("approvals:detail", kwargs={"pk": suspension.approval_id}))

    context = {
        "suspension": suspension,
        "back_url": back_url,
        "reset_url": reverse("approvals:detail", kwargs={"pk": suspension.approval_id}),
        "form": form,
    }
    return render(request, template_name, context)


@login_required
def suspension_delete(request, suspension_id, template_name="approvals/suspension_delete.html"):
    """
    Delete the given suspension.
    """

    siae = get_current_company_or_404(request)
    suspension = get_object_or_404(Suspension.objects.select_related("approval__user"), pk=suspension_id)

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(
        request,
        "back_url",
        fallback_url=reverse("approvals:suspension_action_choice", kwargs={"suspension_id": suspension_id}),
    )

    if request.method == "POST" and request.POST.get("confirm") == "true":
        suspension.delete()
        messages.success(
            request,
            f"La suspension de {suspension.approval.user.get_full_name()} a bien été supprimée.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(reverse("approvals:detail", kwargs={"pk": suspension.approval_id}))

    context = {
        "suspension": suspension,
        "back_url": back_url,
        "reset_url": reverse("approvals:detail", kwargs={"pk": suspension.approval_id}),
        "lost_days": (timezone.localdate() - suspension.start_at).days + 1,
    }
    return render(request, template_name, context)


@login_required
def pe_approval_search(request, template_name="approvals/pe_approval_search.html"):
    """
    Entry point of the `PoleEmploiApproval`'s conversion process which consists of 3 steps
    and allows to convert a `PoleEmploiApproval` into an `Approval`.
    This process is required following the end of the software allowing Pôle emploi to manage
    their approvals.

    Search for a PoleEmploiApproval by number.
    Redirects to the existing Pass if it exists.
    If not, it will ask you to search for an user in order to import the "agrément" as a "PASS IAE".
    """
    approval = None
    form = PoleEmploiApprovalSearchForm(request.GET or None)
    number = None
    siae = get_current_company_or_404(request)
    if not siae.is_subject_to_eligibility_rules:
        raise PermissionDenied()
    back_url = reverse("approvals:pe_approval_search")

    if form.is_valid():
        number = form.cleaned_data["number"]

        # first try to get a matching PASS IAE, and guide the user towards eventual different paths
        approval = Approval.objects.filter(number=number).first()
        if approval:
            job_application = get_user_last_accepted_siae_job_application(approval.user)
            if job_application and job_application.to_company == siae:
                # Suspensions and prolongations links are available in the job application details page.
                application_details_url = reverse(
                    "apply:details_for_company",
                    kwargs={"job_application_id": job_application.pk},
                )
                return HttpResponseRedirect(application_details_url)
            # The employer cannot handle the PASS as it's already used by another one.
            # Suggest him to make a self-prescription. A link is offered in the template.

        else:
            # if no PASS was found, try and find a PoleEmploiApproval.
            approval = PoleEmploiApproval.objects.filter(number=number).first()

        if approval:
            context = {
                "approval": approval,
                "back_url": back_url,
            }
            return render(request, "approvals/pe_approval_search_found.html", context)

    context = {
        "form": form,
        "number": number,
        "siae": siae,
    }
    return render(request, template_name, context)


@login_required
def pe_approval_search_user(request, pe_approval_id, template_name="approvals/pe_approval_search_user.html"):
    """
    2nd step of the PoleEmploiApproval's conversion process.

    Search for a given user by email address.
    """
    siae = get_current_company_or_404(request)
    if not siae.is_subject_to_eligibility_rules:
        raise PermissionDenied()

    pe_approval = get_object_or_404(PoleEmploiApproval, pk=pe_approval_id)

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    form = JobSeekerExistsForm(data=None)

    context = {"back_url": back_url, "form": form, "pe_approval": pe_approval}
    return render(request, template_name, context)


@login_required
def pe_approval_create(request, pe_approval_id):
    """
    Final step of the PoleEmploiApproval's conversion process.

    Create a Approval and a JobApplication out of a (previously created) User and a PoleEmploiApproval.
    """
    siae = get_current_company_or_404(request)
    if not siae.is_subject_to_eligibility_rules:
        raise PermissionDenied()

    pe_approval = get_object_or_404(PoleEmploiApproval, pk=pe_approval_id)

    form = JobSeekerExistsForm(data=request.POST or None)
    if request.method != "POST" or not form.is_valid():
        next_url = reverse(
            "approvals:pe_approval_search_user",
            kwargs={"pe_approval_id": pe_approval_id},
        )
        return HttpResponseRedirect(next_url)

    # If there already is a user with this email, we take it, otherwise we create one
    email = form.cleaned_data["email"]
    job_seeker = User.objects.filter(email__iexact=email).first()
    if not job_seeker:
        job_seeker = User.create_job_seeker_from_pole_emploi_approval(request.user, email, pe_approval)

    # If the PoleEmploiApproval has already been imported, it is not possible to import it again.
    possible_matching_approval = Approval.objects.filter(number=pe_approval.number).order_by("-start_at").first()
    if possible_matching_approval:
        messages.info(request, "Cet agrément a déjà été importé.")
        job_application = JobApplication.objects.filter(approval=possible_matching_approval).first()
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        return HttpResponseRedirect(next_url)

    # It is not possible to attach an approval to a job seeker that already has a valid approval.
    if job_seeker.latest_approval and job_seeker.latest_approval.is_valid():
        messages.error(
            request,
            "Le candidat associé à cette adresse e-mail a déjà un PASS IAE valide.",
        )
        next_url = reverse(
            "approvals:pe_approval_search_user",
            kwargs={"pe_approval_id": pe_approval_id},
        )
        return HttpResponseRedirect(next_url)

    # Then we build the necessary JobApplication for redirection
    now = timezone.now()
    job_application = JobApplication(
        job_seeker=job_seeker,
        to_company=siae,
        state=JobApplicationState.ACCEPTED,
        origin=Origin.PE_APPROVAL,  # This origin is specific to this process.
        sender=request.user,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=siae,
        created_at=now,
        processed_at=now,
    )

    # Then we create an Approval based on the PoleEmploiApproval data
    approval_from_pe = Approval(
        start_at=pe_approval.start_at,
        end_at=pe_approval.end_at,
        user=job_seeker,
        # Only store 12 chars numbers.
        number=pe_approval.number,
        **Approval.get_origin_kwargs(job_application),
    )
    approval_from_pe.save()

    # Link both and save the application
    job_application.approval = approval_from_pe
    job_application.save()

    messages.success(
        request,
        "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.",
        extra_tags="toast",
    )
    next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
    return HttpResponseRedirect(next_url)
