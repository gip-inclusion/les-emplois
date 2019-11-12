from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _
from django.views.decorators.http import require_http_methods

from itou.eligibility.forms.form_v_1_0_0 import EligibilityForm
from itou.job_applications.models import JobApplication
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.perms.user import get_user_info
from itou.www.apply.forms import AcceptForm, AnswerForm, RefusalForm


@login_required
def details_for_siae(
    request, job_application_id, template_name="apply/process_details.html"
):
    """
    Detail of an application for an SIAE with the ability to give an answer.
    """

    queryset = (
        JobApplication.objects.siae_member_required(request.user)
        .select_related(
            "job_seeker",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae",
        )
        .prefetch_related("selected_jobs__appellation")
    )
    job_application = get_object_or_404(queryset, id=job_application_id)

    transition_logs = (
        job_application.logs.select_related("user").all().order_by("timestamp")
    )

    context = {"job_application": job_application, "transition_logs": transition_logs}
    return render(request, template_name, context)


@login_required
@require_http_methods(["POST"])
def process(request, job_application_id):
    """
    Trigger the `process` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    job_application.process(user=request.user)

    next_url = reverse(
        "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
    )
    return HttpResponseRedirect(next_url)


@login_required
def refuse(request, job_application_id, template_name="apply/process_refuse.html"):
    """
    Trigger the `refuse` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    form = RefusalForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_application.refusal_reason = form.cleaned_data["refusal_reason"]
        job_application.answer = form.cleaned_data["answer"]
        job_application.save()

        job_application.refuse(user=request.user)

        messages.success(request, _("Modification effectuée."))

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {"job_application": job_application, "form": form}
    return render(request, template_name, context)


@login_required
def postpone(request, job_application_id, template_name="apply/process_postpone.html"):
    """
    Trigger the `postpone` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    form = AnswerForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        job_application.answer = form.cleaned_data["answer"]
        job_application.save()

        job_application.postpone(user=request.user)

        messages.success(request, _("Modification effectuée."))

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {"job_application": job_application, "form": form}
    return render(request, template_name, context)


@login_required
def accept(request, job_application_id, template_name="apply/process_accept.html"):
    """
    Trigger the `accept` transition.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(queryset, id=job_application_id)

    form = AcceptForm(instance=job_application, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        job_application = form.save()
        job_application.accept(user=request.user)
        # TODO: display another message if the user already have an approval number.
        messages.success(
            request,
            mark_safe(
                _(
                    "Embauche acceptée.<br>"
                    "Il n'est pas nécessaire de demander de numéro d'agrément à votre interlocuteur Pôle emploi.<br>"
                    "Le numéro d'agrément sera indiqué sur cette page - "
                    "vous serez prévenu par email dès qu'il sera disponible.<br>"
                    "Ce numéro pourra être utilisé pour la déclaration de la personne dans l'ASP.<br>"
                )
            ),
        )
        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {"job_application": job_application, "form": form}
    return render(request, template_name, context)


@login_required
def eligibility(
    request, job_application_id, template_name="apply/process_eligibility.html"
):
    """
    Check eligibility.
    """

    queryset = JobApplication.objects.siae_member_required(request.user)
    job_application = get_object_or_404(
        queryset, id=job_application_id, state=JobApplicationWorkflow.STATE_PROCESSING
    )

    user_info = get_user_info(request)
    form = EligibilityForm(
        user_info=user_info,
        job_seeker=job_application.job_seeker,
        data=request.POST or None,
    )
    if request.method == "POST" and form.is_valid():
        form.save_diagnosis()
        messages.success(request, _("Critères d'éligibilité enregistrés !"))
        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.id}
        )
        return HttpResponseRedirect(next_url)

    context = {"job_application": job_application, "form": form}
    return render(request, template_name, context)
