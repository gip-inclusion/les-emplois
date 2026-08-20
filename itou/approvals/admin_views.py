"""
Custom admin views.

We should keep those to a minimum to avoid a future maintenance nightmare.

https://docs.djangoproject.com/en/dev/ref/contrib/admin/#adding-views-to-admin-sites
https://github.com/django/django/blob/master/django/contrib/admin/templates/admin/change_form.html
"""

import datetime
import logging
from collections import defaultdict

from django.contrib import admin, messages
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from itoutils.urls import add_url_params

from itou.approvals.admin_forms import ManuallyAddApprovalFromJobApplicationForm, ProlongationDerogationForm
from itou.approvals.enums import Origin
from itou.approvals.models import Approval, CancelledApproval, Prolongation, Suspension
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.admin import add_support_remark_to_obj
from itou.utils.apis import enums as api_enums
from itou.utils.emails import get_email_text_template
from itou.utils.tokens import prolongation_derogation_token_generator
from itou.utils.urls import get_absolute_url


logger = logging.getLogger("itou.approvals.admin")


def _admin_context(request, model_admin, *, title, **extra):
    """Build the context every custom admin view needs to render an admin template."""
    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    return admin_site.each_context(request) | {
        "admin_site": admin_site.name,
        "app_label": opts.app_label,
        "has_view_permission": model_admin.has_view_permission(request),
        "media": model_admin.media,
        "opts": opts,
        "subtitle": None,
        "title": title,
        **extra,
    }


def manually_add_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_add_approval.html"
):
    """
    Custom admin view to manually add an approval.
    """

    app_label = model_admin.model._meta.app_label
    has_perm = request.user.has_perm(f"{app_label}.handle_manual_approval_requests")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationState.ACCEPTED,
        approval=None,
        approval_manually_refused_at=None,
        approval_manually_refused_by=None,
        approval_number_sent_by_email=False,
    )

    if job_application.eligibility_diagnosis is None:
        messages.error(
            request, "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostic d'éligibilité."
        )
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    initial = {
        "start_at": job_application.hiring_start_at,
        "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
    }
    form = ManuallyAddApprovalFromJobApplicationForm(initial=initial, data=request.POST or None)
    fieldsets = [(None, {"fields": list(form.base_fields)})]
    adminForm = admin.helpers.AdminForm(form, fieldsets, {})

    if request.method == "POST" and form.is_valid():
        if job_application.job_seeker.has_valid_approval:
            raise PermissionDenied

        form.instance.user = job_application.job_seeker
        form.instance.origin = Origin.ADMIN
        form.instance.created_by = request.user
        form.instance.eligibility_diagnosis = job_application.eligibility_diagnosis
        for field, value in Approval.get_origin_kwargs(job_application).items():
            setattr(form.instance, field, value)
        approval = form.save()
        job_application.approval = approval
        job_application.manually_deliver_approval(delivered_by=request.user)
        messages.success(request, f"Le PASS IAE {approval.number_with_spaces} a bien été créé et envoyé par e-mail.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    context = _admin_context(
        request,
        model_admin,
        title="Ajout manuel d'un numéro d'agrément",
        add=True,
        adminform=adminForm,
        errors=admin.helpers.AdminErrorList(form, {}),
        form=form,
        job_application=job_application,
    )
    return render(request, template_name, context)


def manually_refuse_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_refuse_approval.html"
):
    """
    Custom admin view to manually refuse an approval (in the case of a job seeker in waiting period).
    """

    app_label = model_admin.model._meta.app_label
    has_perm = request.user.has_perm(f"{app_label}.handle_manual_approval_requests")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationState.ACCEPTED,
        approval=None,
        approval_manually_delivered_by=None,
        approval_number_sent_by_email=False,
    )

    if job_application.job_seeker.has_valid_approval:
        raise PermissionDenied

    if request.method == "POST" and request.POST.get("confirm") == "yes":
        job_application.manually_refuse_approval(refused_by=request.user)
        messages.success(request, "Délivrance du PASS IAE refusée.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    # Display a preview of the email that will be send.
    email_subject_template = get_email_text_template(
        "approvals/email/refuse_manually_subject.txt", {"job_application": job_application}
    )
    email_body_template = get_email_text_template(
        "approvals/email/refuse_manually_body.txt",
        {
            "job_application": job_application,
            "job_application_url": get_absolute_url(
                reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
            ),
            "search_url": get_absolute_url(reverse("search:prescribers_home")),
        },
    )

    context = _admin_context(
        request,
        model_admin,
        title="Confirmer le refus manuel d'un numéro d'agrément",
        add=True,
        email_body_template=email_body_template,
        email_subject_template=email_subject_template,
        job_application=job_application,
    )
    return render(request, template_name, context)


def _clip_approval_dependency(approval, model, end_date, acting_user):
    _, deletions = model.objects.filter(approval=approval, start_at__gte=end_date).delete()
    if deletions:
        logger.info(
            "Terminating approval pk=%(approval_id)d, deleting %(deletions)d future %(model_name)s.",
            {
                "approval_id": approval.pk,
                "deletions": deletions[model._meta.label],
                "model_name": model._meta.label,
            },
        )
    try:
        obj = model.objects.in_progress().filter(approval=approval).get()
    except model.DoesNotExist:
        pass
    else:
        logger.info(
            "Terminating approval pk=%(approval_id)d, "
            "setting %(model_name)s pk=%(model_id)d end_at=%(end_at)s "
            "(was %(initial_end_at)s).",
            {
                "approval_id": approval.pk,
                "model_name": obj._meta.label,
                "model_id": obj.pk,
                "end_at": end_date,
                "initial_end_at": obj.end_at,
            },
        )
        obj.end_at = end_date
        obj.updated_by = acting_user
        obj.save(update_fields=["end_at", "updated_at", "updated_by"])


def terminate_approval(request, model_admin, approval_id):
    opts = model_admin.model._meta
    app_label = opts.app_label
    codename = get_permission_codename("change", opts)
    if not request.user.has_perm(f"{app_label}.{codename}"):
        raise PermissionDenied

    new_end = timezone.localdate()
    approval = get_object_or_404(Approval, pk=approval_id, end_at__gte=new_end)
    _clip_approval_dependency(approval, Prolongation, new_end, request.user)
    _clip_approval_dependency(approval, Suspension, new_end, request.user)
    logger.info(
        "Terminating approval pk=%(approval_id)d, end_at=%(end_at)s (was %(initial_end_at)s).",
        {
            "approval_id": approval.pk,
            "initial_end_at": approval.end_at,
            "end_at": new_end,
        },
    )
    approval.end_at = new_end
    approval.save(update_fields=["end_at", "updated_at"])
    add_support_remark_to_obj(approval, f"{new_end} : PASS IAE clôturé par {request.user.get_full_name()}.")
    return HttpResponseRedirect(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))


def prolongation_derogation(
    request, model_admin, approval_id, template_name="admin/approvals/prolongation_derogation.html"
):
    """Admin view to issue a link that allows an employer to declare an out-of-time-limits prolongation.

    Only the prolongation deadline is waived, see `Approval.needs_prolongation_derogation`.
    """

    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    codename = get_permission_codename("change", opts)
    if not request.user.has_perm(f"{opts.app_label}.{codename}"):
        raise PermissionDenied

    approval = get_object_or_404(Approval.objects.select_related("user").with_assigned_company(), pk=approval_id)

    if not approval.needs_prolongation_derogation:
        PROLONGATION_STILL_POSSIBLE = (
            "Ce PASS IAE est dans les délais, l’employeur peut déclarer la prolongation sans lien de dérogation."
        )
        blocker = approval.prolongation_blocker
        messages.error(request, blocker.label if blocker else PROLONGATION_STILL_POSSIBLE)
        return HttpResponseRedirect(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))

    form = ProlongationDerogationForm(
        approval=approval,
        admin_site=admin_site,
        data=request.POST or None,
        # The company handling the PASS IAE is the expected one in the
        # majority of cases, but the support can still pick another one
        initial={"company": approval.assigned_company},
    )
    derogation_link = None
    if request.method == "POST" and form.is_valid():
        company = form.cleaned_data["company"]
        token = prolongation_derogation_token_generator.make_token(approval=approval, company=company)
        derogation_link = get_absolute_url(
            reverse("approvals:prolongation_derogation", kwargs={"approval_id": approval.pk, "token": token})
        )
        add_support_remark_to_obj(
            approval,
            f"{timezone.localdate()} : lien de demande de prolongation hors délais généré par "
            f"{request.user.get_full_name()} pour l’entreprise {company.pk} — {company.display_name}.",
        )
        logger.info(
            "staff user=%(user_id)d issued a prolongation derogation link "
            "for approval=%(approval_id)d company=%(company_id)d.",
            {"user_id": request.user.pk, "approval_id": approval.pk, "company_id": company.pk},
        )
        messages.success(request, "Le lien de demande de prolongation a bien été généré.")
    timeout = datetime.timedelta(seconds=prolongation_derogation_token_generator.timeout)
    context = _admin_context(
        request,
        model_admin,
        title=(
            f"Générer un lien de demande de prolongation pour "
            f"le PASS IAE {approval.number} ({approval.user.get_full_name()})"
        ),
        approval=approval,
        # `add` and `original` drive the last breadcrumb of admin/change_form.html, `errors` its
        # “Error:” page <title> prefix.
        add=False,
        original=approval,
        errors=admin.helpers.AdminErrorList(form, {}),
        derogation_link=derogation_link,
        expires_at=timezone.localdate() + timeout if derogation_link else None,
        form=form,
    )
    return render(request, template_name, context)


def _compute_send_approvals_to_pe_stats(model, list_url):
    today = timezone.localdate()

    def _format_value(value, total):
        if not value:
            return str(value)
        if not total:
            return "-"
        return f"{value} ({100 * value / total:.2f} %)"

    counts = model.objects.aggregate(
        total=Count("pk"),
        # Count by status
        pe_notify_pending=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.PENDING)),
        pe_notify_ready=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.READY)),
        pe_notify_should_retry=Count(
            "pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY)
        ),
        pe_notify_error=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)),
        pe_notify_success=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)),
        # More infos on PENDING
        pe_notify_pending_in_future=Count(
            "pk",
            filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.PENDING, start_at__gt=today),
        ),
    )
    errors_infos = defaultdict(lambda: defaultdict(dict))
    for endpoint, exit_code, count in (
        model.objects.filter(pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)
        .values_list("pe_notification_endpoint", "pe_notification_exit_code")
        .annotate(count=Count("pk"))
    ):
        errors_infos[endpoint].setdefault("value", 0)
        errors_infos[endpoint]["value"] += count
        errors_infos[endpoint]["infos"][exit_code] = {"value": count}
    # Prevent further defaulting to enable its use in Django template
    errors_infos.default_factory = None
    # Adapt dictionnary value to add percentages
    for end_point, end_point_infos in errors_infos.items():
        end_point_url_params = {"pe_notification_status": "notification_error", "pe_notification_endpoint": end_point}
        for exit_code, exit_code_infos in end_point_infos["infos"].items():
            exit_code_infos["value"] = _format_value(exit_code_infos["value"], end_point_infos["value"])
            if exit_code is None:
                exit_code_url_params = {**end_point_url_params, "pe_notification_exit_code__isnull": 1}
            else:
                exit_code_url_params = {**end_point_url_params, "pe_notification_exit_code": exit_code}
            exit_code_infos["url"] = add_url_params(list_url, exit_code_url_params)
        end_point_infos["value"] = _format_value(end_point_infos["value"], counts["pe_notify_error"])
        end_point_infos["url"] = add_url_params(list_url, end_point_url_params)

    stats = {
        "name": model._meta.verbose_name_plural,
        "total": counts["total"],
        "infos": {
            "En attente": {
                "value": _format_value(counts["pe_notify_pending"], counts["total"]),
                "infos": {
                    "Démarre dans le futur": {
                        "value": _format_value(counts["pe_notify_pending_in_future"], counts["pe_notify_pending"]),
                        "url": add_url_params(
                            list_url, {"pe_notification_status": "notification_pending", "start_at__gt": today}
                        ),
                    },
                },
                "url": add_url_params(list_url, {"pe_notification_status": "notification_pending"}),
            },
            "Prêt à envoyer": {
                "value": _format_value(counts["pe_notify_ready"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_ready"}),
            },
            "À réessayer": {
                "value": _format_value(counts["pe_notify_should_retry"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_should_retry"}),
            },
            "En erreur": {
                "value": _format_value(counts["pe_notify_error"], counts["total"]),
                "infos": errors_infos,
                "url": add_url_params(list_url, {"pe_notification_status": "notification_error"}),
            },
            "Succès": {
                "value": _format_value(counts["pe_notify_success"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_success"}),
            },
        },
    }
    return stats


def send_approvals_to_pe_stats(request):
    context_data = {
        **admin.site.each_context(request),
        "title": "État de synchronisation avec France Travail",
        "subtitle": None,
        "stats": [
            _compute_send_approvals_to_pe_stats(Approval, list_url=reverse("admin:approvals_approval_changelist")),
            _compute_send_approvals_to_pe_stats(
                CancelledApproval, list_url=reverse("admin:approvals_cancelledapproval_changelist")
            ),
        ],
    }
    return render(request, "admin/approvals/send_approvals_to_pe_stats.html", context_data)
