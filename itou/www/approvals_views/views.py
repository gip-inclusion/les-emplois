from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.generic import DetailView, ListView

from itou.approvals.models import Approval, PoleEmploiApproval, Suspension
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.pagination import ItouPaginator
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import UserExistsForm
from itou.www.approvals_views.forms import (
    ApprovalForm,
    DeclareProlongationForm,
    PoleEmploiApprovalSearchForm,
    SuspensionForm,
)


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
        context_data = super().get_context_data(**kwargs)
        context_data["siae"] = self.siae
        return context_data

    # TODO(alaurent) : An Employee model linked to the siae, Approval and JobSeeker would make things easier here
    def get_job_application(self, approval):
        return (
            JobApplication.objects.filter(
                job_seeker=approval.user,
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_siae=self.siae,
                approval=approval,
            )
            .select_related("eligibility_diagnosis")
            .first()
        )


class ApprovalDetailView(ApprovalBaseViewMixin, DetailView):
    model = Approval
    queryset = Approval.objects.select_related("user")
    template_name = "approvals/detail.html"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["approval_can_be_suspended_by_siae"] = self.object.can_be_suspended_by_siae(self.siae)
        context_data["hire_by_other_siae"] = not self.object.user.last_hire_was_made_by_siae(self.siae)
        context_data["approval_can_be_prolonged_by_siae"] = self.object.can_be_prolonged_by_siae(self.siae)
        job_application = self.get_job_application(self.object)
        context_data["job_application"] = job_application
        if job_application:
            context_data["eligibility_diagnosis"] = job_application.get_eligibility_diagnosis()
        context_data["all_job_applications"] = (
            JobApplication.objects.filter(
                job_seeker=self.object.user,
                to_siae=self.siae,
            )
            .select_related("sender")
            .prefetch_related("selected_jobs")
        )
        return context_data


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
        context_data = super().get_context_data(**kwargs)
        context_data["filters_form"] = self.form
        context_data["filters_counter"] = self.form.get_filters_counter()
        return context_data


@login_required
def display_printable_approval(request, approval_id, template_name="approvals/printable_approval.html"):
    siae = get_current_siae_or_404(request)

    queryset = Approval.objects.select_related("user")
    approval = get_object_or_404(queryset, pk=approval_id)

    job_applications_queryset = JobApplication.objects.select_related("eligibility_diagnosis")
    job_application = get_object_or_404(
        job_applications_queryset,
        job_seeker=approval.user,
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        to_siae=siae,
        approval=approval,
    )

    # TODO(alaurent) We could probably just use "if not siae.is_subject_to_eligibility_rules"
    # Fix this when refactoring the database
    if not job_application.can_display_approval:
        # Message only visible in DEBUG
        raise Http404("Nous sommes au regret de vous informer que vous ne pouvez pas afficher cet agrément.")

    diagnosis = job_application.get_eligibility_diagnosis()
    diagnosis_author = None
    diagnosis_author_org = None
    diagnosis_author_org_name = None

    if diagnosis:
        diagnosis_author = diagnosis.author.get_full_name()
        diagnosis_author_org = diagnosis.author_prescriber_organization or diagnosis.author_siae
        if diagnosis_author_org:
            diagnosis_author_org_name = diagnosis_author_org.display_name

    if not diagnosis and approval.originates_from_itou:
        # On November 30th, 2021, AI were delivered a PASS IAE
        # without a diagnosis for all of their employees.
        # We want to raise an error if the approval of the pass originates from our side, but
        # is not from the AI stock, as it should not happen.
        # We may have to add conditions there in case of new mass imports.
        if not approval.is_from_ai_stock:
            # Keep track of job applications without a proper eligibility diagnosis because
            # it shouldn't happen.
            # If this occurs too much we may have to change `can_display_approval()`
            # and investigate a lot more about what's going on.
            # See also migration `0035_link_diagnoses.py`.
            raise Exception(
                f"Job application={job_application.pk} comes from itou, "
                "had no eligibility diagnosis and also was not mass-imported."
            )

    context = {
        "approval": approval,
        "itou_assistance_url": global_constants.ITOU_ASSISTANCE_URL,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org_name": diagnosis_author_org_name,
        "siae": siae,
        "job_seeker": approval.user,
    }
    return render(request, template_name, context)


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
    }
    return render(request, template_name, context)


@login_required
def suspend(request, approval_id, template_name="approvals/suspend.html"):
    """
    Suspend the given approval.
    """

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

    form = SuspensionForm(approval=suspension.approval, siae=siae, instance=suspension, data=request.POST or None)

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
                    "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
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
        next_url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": pe_approval_id})
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
        messages.error(request, "Le candidat associé à cette adresse e-mail a déjà un PASS IAE valide.")
        next_url = reverse("approvals:pe_approval_search_user", kwargs={"pe_approval_id": pe_approval_id})
        return HttpResponseRedirect(next_url)

    with transaction.atomic():

        # Then we create an Approval based on the PoleEmploiApproval data
        approval_from_pe = Approval(
            start_at=pe_approval.start_at,
            end_at=pe_approval.end_at,
            user=job_seeker,
            # Only store 12 chars numbers.
            number=pe_approval.number,
        )
        approval_from_pe.save()

        # Then we create the necessary JobApplication for redirection
        job_application = JobApplication(
            job_seeker=job_seeker,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=approval_from_pe,
            created_from_pe_approval=True,  # This flag is specific to this process.
            sender=request.user,
            sender_kind=SenderKind.SIAE_STAFF,
            sender_siae=siae,
        )
        job_application.save()

    messages.success(request, "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.")
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
    return HttpResponseRedirect(next_url)
