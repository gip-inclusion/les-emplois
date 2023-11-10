"""
Custom admin views.

We should keep those to a minimum to avoid a future maintenance nightmare.

https://docs.djangoproject.com/en/dev/ref/contrib/admin/#adding-views-to-admin-sites
https://github.com/django/django/blob/master/django/contrib/admin/templates/admin/change_form.html
"""

from django.contrib import admin, messages
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from itou.approvals.admin_forms import ManuallyAddApprovalFromJobApplicationForm
from itou.approvals.enums import Origin
from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.utils.emails import get_email_text_template


def manually_add_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_add_approval.html"
):
    """
    Custom admin view to manually add an approval.
    """

    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    app_label = opts.app_label
    codename = get_permission_codename("add", opts)
    has_perm = request.user.has_perm(f"{app_label}.{codename}")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        approval=None,
        approval_manually_refused_at=None,
        approval_manually_refused_by=None,
        approval_number_sent_by_email=False,
    )

    if job_application.eligibility_diagnosis is None:
        messages.error(
            request, "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostique d'éligibilité."
        )
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    initial = {
        "start_at": job_application.hiring_start_at,
        "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
        "user": job_application.job_seeker.pk,
        "created_by": request.user.pk,
        "origin": Origin.ADMIN,
        "eligibility_diagnosis": job_application.eligibility_diagnosis,
    }
    form = ManuallyAddApprovalFromJobApplicationForm(initial=initial, data=request.POST or None)
    fieldsets = [(None, {"fields": list(form.base_fields)})]
    adminForm = admin.helpers.AdminForm(form, fieldsets, {})

    if request.method == "POST" and form.is_valid():
        approval = form.save()
        job_application.approval = approval
        job_application.manually_deliver_approval(delivered_by=request.user)
        messages.success(request, f"Le PASS IAE {approval.number_with_spaces} a bien été créé et envoyé par e-mail.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    context = {
        "add": True,
        "adminform": adminForm,
        "admin_site": admin_site.name,
        "app_label": app_label,
        "errors": admin.helpers.AdminErrorList(form, {}),
        "form": form,
        "job_application": job_application,
        "media": model_admin.media,
        "opts": opts,
        "title": "Ajout manuel d'un numéro d'agrément",
        **admin_site.each_context(request),
    }
    return render(request, template_name, context)


def manually_refuse_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_refuse_approval.html"
):
    """
    Custom admin view to manually refuse an approval (in the case of a job seeker in waiting period).
    """

    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    app_label = opts.app_label
    codename = get_permission_codename("add", opts)
    has_perm = request.user.has_perm(f"{app_label}.{codename}")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        approval=None,
        approval_manually_delivered_by=None,
        approval_number_sent_by_email=False,
    )

    if request.method == "POST" and request.POST.get("confirm") == "yes":
        job_application.manually_refuse_approval(refused_by=request.user)
        messages.success(request, "Délivrance du PASS IAE refusée.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    # Display a preview of the email that will be send.
    email_subject_template = get_email_text_template(
        "approvals/email/refuse_manually_subject.txt", {"job_application": job_application}
    )
    email_body_template = get_email_text_template(
        "approvals/email/refuse_manually_body.txt", {"job_application": job_application}
    )

    context = {
        "add": True,
        "admin_site": admin_site.name,
        "app_label": app_label,
        "email_body_template": email_body_template,
        "email_subject_template": email_subject_template,
        "job_application": job_application,
        "media": model_admin.media,
        "opts": opts,
        "title": "Confirmer le refus manuel d'un numéro d'agrément",
        **admin_site.each_context(request),
    }
    return render(request, template_name, context)
