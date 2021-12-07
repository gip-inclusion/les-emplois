from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template.response import SimpleTemplateResponse
from django.urls import reverse
from django.utils.text import slugify

from itou.approvals.models import Approval, ApprovalsWrapper, PoleEmploiApproval, Suspension
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.models import User
from itou.utils.pdf import HtmlToPdf
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import UserExistsForm
from itou.www.approvals_views.forms import DeclareProlongationForm, PoleEmploiApprovalSearchForm, SuspensionForm


@login_required
def approval_as_pdf(request, job_application_id, template_name="approvals/approval_as_pdf.html"):
    """
    Displays the approval in pdf format
    """
    siae = get_current_siae_or_404(request)

    queryset = JobApplication.objects.select_related("job_seeker", "eligibility_diagnosis", "approval", "to_siae")
    job_application = get_object_or_404(queryset, pk=job_application_id, to_siae=siae)

    if not job_application.can_download_approval_as_pdf:
        # Message only visible in DEBUG
        raise Http404("Nous sommes au regret de vous informer que vous ne pouvez pas télécharger cet agrément.")

    diagnosis = job_application.get_eligibility_diagnosis()
    diagnosis_author = None
    diagnosis_author_org = None
    diagnosis_author_org_name = None

    if diagnosis:
        diagnosis_author = diagnosis.author.get_full_name()
        diagnosis_author_org = diagnosis.author_prescriber_organization or diagnosis.author_siae
        if diagnosis_author_org:
            diagnosis_author_org_name = diagnosis_author_org.display_name

    if not diagnosis and job_application.approval and job_application.approval.originates_from_itou:
        # On November 30th, 2021, AI were delivered a PASS IAE
        # without a diagnosis for all of their employees.
        if not job_application.approval.is_from_ai_stock:
            # Keep track of job applications without a proper eligibility diagnosis because
            # it shouldn't happen.
            # If this occurs too much we may have to change `can_download_approval_as_pdf()`
            # and investigate a lot more about what's going on.
            # See also migration `0035_link_diagnoses.py`.
            raise ObjectDoesNotExist("Job application %s has no eligibility diagnosis." % job_application.pk)

    # The PDFShift API can load styles only if it has the full URL.
    base_url = request.build_absolute_uri("/")[:-1]

    if settings.DEBUG:
        # Use staging or production styles when working locally
        # as PDF shift can't access local files.
        base_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_STAGING_DN}"

    context = {
        "approval": job_application.approval,
        "base_url": base_url,
        "assistance_url": settings.ITOU_ASSISTANCE_URL,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org_name": diagnosis_author_org_name,
        "siae": job_application.to_siae,
        "job_seeker": job_application.job_seeker,
    }

    html = SimpleTemplateResponse(template=template_name, context=context).rendered_content

    full_name_slug = slugify(job_application.job_seeker.get_full_name())
    filename = f"{full_name_slug}-pass-iae.pdf"

    with HtmlToPdf(html, autoclose=False) as transformer:
        return FileResponse(transformer.file, as_attachment=True, filename=filename)


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
        approvals_wrapper = ApprovalsWrapper(number=number)
        approval = approvals_wrapper.latest_approval

        if approval:
            if approval.is_pass_iae:
                job_application = approval.user.last_accepted_job_application
                if job_application and job_application.to_siae == siae:
                    # Suspensions and prolongations links are available in the job application details page.
                    application_details_url = reverse(
                        "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
                    )
                    return HttpResponseRedirect(application_details_url)
                # The employer cannot handle the PASS as it's already used by another one.
                # Suggest him to make a self-prescription. A link is offered in the template.

            context = {
                "approval": approval,
                "back_url": back_url,
                "form": form,
                "number": number,
                "siae": siae,
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
    possible_matching_approval = Approval.objects.filter(number=pe_approval.number[:12]).order_by("-start_at").first()
    if possible_matching_approval:
        messages.info(request, "Cet agrément a déjà été importé.")
        job_application = JobApplication.objects.filter(approval=possible_matching_approval).first()
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        return HttpResponseRedirect(next_url)

    # It is not possible to attach an approval to a job seeker that already has a valid approval.
    if job_seeker.approvals_wrapper.has_valid and job_seeker.approvals_wrapper.latest_approval.is_pass_iae:
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
            number=pe_approval.number[:12],
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
            sender_kind=JobApplication.SENDER_KIND_SIAE_STAFF,
            sender_siae=siae,
        )
        job_application.save()

    messages.success(request, "L'agrément a bien été importé, vous pouvez désormais le prolonger ou le suspendre.")
    next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
    return HttpResponseRedirect(next_url)
