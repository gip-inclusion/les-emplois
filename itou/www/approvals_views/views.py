import urllib.parse
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView

from itou.approvals import enums as approvals_enums
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.models import Approval, PoleEmploiApproval, Suspension
from itou.files.models import File
from itou.job_applications.enums import Origin, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.pagination import ItouPaginator
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.storage.s3 import S3Upload
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import UserExistsForm
from itou.www.approvals_views.forms import (
    ApprovalForm,
    DeclareProlongationForm,
    PoleEmploiApprovalSearchForm,
    SuspensionForm,
)


SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE = timedelta(days=365)


class ApprovalBaseViewMixin(LoginRequiredMixin):
    model = Approval

    def __init__(self):
        super().__init__()
        self.siae = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if request.user.is_authenticated:
            self.siae = get_current_siae_or_404(request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["siae"] = self.siae
        return context

    def get_job_application(self, approval):
        return (
            JobApplication.objects.filter(
                job_seeker=approval.user,
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_siae=self.siae,
                approval=approval,
            )
            .select_related(
                "eligibility_diagnosis",
                "eligibility_diagnosis__author_siae",
                "eligibility_diagnosis__author_prescriber_organization",
                "eligibility_diagnosis__job_seeker",
            )
            .first()
        )


class ApprovalDetailView(ApprovalBaseViewMixin, DetailView):
    model = Approval
    queryset = Approval.objects.select_related("user").prefetch_related("suspension_set")
    template_name = "approvals/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        approval = self.object
        job_application = self.get_job_application(self.object)

        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["can_edit_personal_information"] = self.request.user.can_edit_personal_information(approval.user)
        context["approval_can_be_suspended_by_siae"] = approval.can_be_suspended_by_siae(self.siae)
        context["hire_by_other_siae"] = not approval.user.last_hire_was_made_by_siae(self.siae)
        context["approval_can_be_prolonged_by_siae"] = approval.can_be_prolonged_by_siae(self.siae)
        context["job_application"] = job_application
        context["matomo_custom_title"] = "Profil salarié"
        if job_application:
            context["eligibility_diagnosis"] = job_application.get_eligibility_diagnosis()

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
                to_siae=self.siae,
            )
            .select_related("sender")
            .prefetch_related("selected_jobs")
        )
        return context


class ApprovalListView(ApprovalBaseViewMixin, ListView):
    template_name = "approvals/list.html"
    paginate_by = 10
    paginator_class = ItouPaginator

    def __init__(self):
        super().__init__()
        self.form = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.siae:
            self.form = ApprovalForm(self.siae.pk, self.request.GET)

    def get_queryset(self):
        form_filters = []
        if self.form.is_valid():
            form_filters = self.form.get_qs_filters()
        return super().get_queryset().filter(*form_filters)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters_form"] = self.form
        context["filters_counter"] = self.form.get_filters_counter()
        return context


class ApprovalPrintableDisplay(ApprovalBaseViewMixin, TemplateView):
    template_name = "approvals/printable_approval.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        queryset = Approval.objects.select_related("user")
        approval = get_object_or_404(queryset, pk=self.kwargs["approval_id"])

        if not self.siae.is_subject_to_eligibility_rules:
            # Message only visible in DEBUG
            raise Http404("Nous sommes au regret de vous informer que vous ne pouvez pas afficher cet agrément.")

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
                "itou_assistance_url": global_constants.ITOU_ASSISTANCE_URL,
                "diagnosis_author": diagnosis_author,
                "diagnosis_author_org_name": diagnosis_author_org_name,
                "matomo_custom_title": "Attestation de délivrance d'agrément",
            }
        )
        return context


@login_required
def declare_prolongation(request, approval_id, template_name="approvals/declare_prolongation.html"):
    """
    Declare a prolongation for the given approval.
    """

    siae = get_current_siae_or_404(request)
    approval = get_object_or_404(Approval, pk=approval_id)

    if not approval.can_be_prolonged_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    preview = False

    form = DeclareProlongationForm(approval=approval, siae=siae, data=request.POST or None)
    s3_upload = S3Upload(kind="prolongation_report")

    if request.method == "POST" and form.is_valid():
        prolongation = form.save(commit=False)
        prolongation.created_by = request.user
        prolongation.declared_by = request.user
        prolongation.declared_by_siae = form.siae
        prolongation.validated_by = form.validated_by

        if request.POST.get("edit"):
            preview = False
        if request.POST.get("preview"):
            preview = True
        elif request.POST.get("save"):
            if key := form.cleaned_data.get("report_file_path"):
                file = File(key, timezone.now())
                prolongation.report_file = file
                file.save()

            prolongation.save()

            if form.cleaned_data.get("email"):
                # Send an email w/o DB changes
                prolongation.notify_authorized_prescriber()

            messages.success(request, "Déclaration de prolongation enregistrée.")
            return HttpResponseRedirect(back_url)

    context = {
        "approval": approval,
        "back_url": back_url,
        "form": form,
        "preview": preview,
        "s3_upload": s3_upload,
        "unfold_details": form.data.get("reason") in PROLONGATION_REPORT_FILE_REASONS,
    }

    return render(request, template_name, context)


class DeclareProlongationHTMXFragmentView(TemplateView):
    """
    HTMX interactions on dynamic parts of the prolongation declaration form
    """

    # Sometimes validation errors don't have to be displayed after loading of an HTMX fragment
    # and we only want to display them after a "main" validation action (final validation of form)
    clear_errors_after_loading = True

    # if 'clear_errors_after_loading' is true, select form errors to be cleared
    clear_errors = []

    def _clear_errors(self):
        # Clear given form errors if validation is not needed (but triggered)
        for error_key in self.clear_errors:
            self.form.errors.pop(error_key, None)

    def setup(self, request, approval_id, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if request.user.is_authenticated:
            self.siae = get_current_siae_or_404(request)
            self.approval = get_object_or_404(Approval, pk=approval_id)

        if not self.approval.can_be_prolonged_by_siae(self.siae):
            raise PermissionDenied()

        self.form = DeclareProlongationForm(approval=self.approval, siae=self.siae, data=request.POST or None)
        self.s3_upload = S3Upload(kind="prolongation_report")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context |= {
            "approval": self.approval,
            "form": self.form,
            "s3_upload": self.s3_upload,
        }
        return context

    def post(self, request, *args, **kwargs):
        if self.clear_errors_after_loading:
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


class CheckPrescriberEmailView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/declaration_prescriber_email.html"


class CheckContactDetailsView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/declaration_contact_details.html"
    clear_errors = ("contact_email", "contact_phone")


class ToggledUploadPanelView(DeclareProlongationHTMXFragmentView):
    template_name = "approvals/includes/declaration_upload_panel.html"
    clear_errors = ("email",)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context |= {
            "unfold_details": self.form.data.get("reason") in PROLONGATION_REPORT_FILE_REASONS,
        }
        return context


@login_required
def suspend(request, approval_id, template_name="approvals/suspend.html"):
    siae = get_current_siae_or_404(request)
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
            messages.success(request, "Suspension effectuée.")
            return HttpResponseRedirect(back_url)

    context = {
        "approval": approval,
        "back_url": back_url,
        "form": form,
        "preview": preview,
    }
    return render(request, template_name, context)


@login_required
def suspension_update(request, suspension_id, template_name="approvals/suspension_update.html"):
    """
    Edit the given suspension.
    """

    siae = get_current_siae_or_404(request)
    suspension = get_object_or_404(Suspension, pk=suspension_id)

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
        messages.success(request, "Modification de suspension effectuée.")
        return HttpResponseRedirect(back_url)

    context = {
        "suspension": suspension,
        "back_url": back_url,
        "form": form,
    }
    return render(request, template_name, context)


@login_required
def suspension_delete(request, suspension_id, template_name="approvals/suspension_delete.html"):
    """
    Delete the given suspension.
    """

    siae = get_current_siae_or_404(request)
    suspension = get_object_or_404(Suspension, pk=suspension_id)

    if not suspension.can_be_handled_by_siae(siae):
        raise PermissionDenied()

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    if request.method == "POST" and request.POST.get("confirm") == "true":
        suspension.delete()
        messages.success(request, "Annulation de suspension effectuée.")
        return HttpResponseRedirect(back_url)

    context = {
        "suspension": suspension,
        "back_url": back_url,
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
    siae = get_current_siae_or_404(request)
    back_url = reverse("approvals:pe_approval_search")

    if form.is_valid():
        number = form.cleaned_data["number"]

        # first try to get a matching PASS IAE, and guide the user towards eventual different paths
        approval = Approval.objects.filter(number=number).first()
        if approval:
            job_application = approval.user.last_accepted_job_application
            if job_application and job_application.to_siae == siae:
                # Suspensions and prolongations links are available in the job application details page.
                application_details_url = reverse(
                    "apply:details_for_siae",
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
    pe_approval = get_object_or_404(PoleEmploiApproval, pk=pe_approval_id)

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    form = UserExistsForm(data=None)

    context = {"back_url": back_url, "form": form, "pe_approval": pe_approval}
    return render(request, template_name, context)


@login_required
def pe_approval_create(request, pe_approval_id):
    """
    Final step of the PoleEmploiApproval's conversion process.

    Create a Approval and a JobApplication out of a (previously created) User and a PoleEmploiApproval.
    """
    siae = get_current_siae_or_404(request)
    pe_approval = get_object_or_404(PoleEmploiApproval, pk=pe_approval_id)

    form = UserExistsForm(data=request.POST or None)
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
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
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

    # Then we create an Approval based on the PoleEmploiApproval data
    approval_from_pe = Approval(
        start_at=pe_approval.start_at,
        end_at=pe_approval.end_at,
        user=job_seeker,
        # Only store 12 chars numbers.
        number=pe_approval.number,
        origin=approvals_enums.Origin.PE_APPROVAL,
    )
    approval_from_pe.save()

    # Then we create the necessary JobApplication for redirection
    job_application = JobApplication(
        job_seeker=job_seeker,
        to_siae=siae,
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        approval=approval_from_pe,
        origin=Origin.PE_APPROVAL,  # This origin is specific to this process.
        sender=request.user,
        sender_kind=SenderKind.SIAE_STAFF,
        sender_siae=siae,
    )
    job_application.save()

    messages.success(
        request,
        "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.",
    )
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
    return HttpResponseRedirect(next_url)
