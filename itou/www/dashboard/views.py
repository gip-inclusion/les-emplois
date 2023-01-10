from allauth.account.views import PasswordChangeView
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.institutions.models import Institution
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import EvaluatedSiae, EvaluationCampaign
from itou.siaes.models import Siae, SiaeFinancialAnnex
from itou.utils import constants as global_constants
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url
from itou.www.dashboard.forms import (
    EditJobSeekerInfoForm,
    EditNewJobAppEmployersNotificationForm,
    EditUserEmailForm,
    EditUserInfoForm,
)


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):
    can_show_financial_annexes = False
    can_show_employee_records = False
    job_applications_categories = []
    num_rejected_employee_records = 0
    active_campaigns = []
    campaign_in_progress = False
    evaluated_siae_notifications = EvaluatedSiae.objects.none()
    show_previous_year_financial_annex_info = False

    # `current_org` can be a Siae, a PrescriberOrganization or an Institution.
    current_org = None

    if request.user.is_siae_staff:
        current_org = get_current_siae_or_404(request)
        can_show_financial_annexes = current_org.convention_can_be_accessed_by(request.user)
        can_show_employee_records = current_org.can_use_employee_record
        active_campaigns = EvaluatedSiae.objects.for_siae(current_org).in_progress()
        evaluated_siae_notifications = (
            EvaluatedSiae.objects.for_siae(current_org)
            .exclude(notified_at=None)
            .filter(
                Q(evaluation_campaign__ended_at=None)
                | Q(evaluation_campaign__ended_at__gte=timezone.now() - CAMPAIGN_VIEWABLE_DURATION)
            )
            .select_related("evaluation_campaign")
        )

        job_applications_categories = [
            {
                "name": "À traiter",
                "states": [JobApplicationWorkflow.STATE_NEW, JobApplicationWorkflow.STATE_PROCESSING],
                "icon": "ri-user-add-line",
                "badge": "badge-accent-02",
            },
            {
                "name": "En attente",
                "states": [JobApplicationWorkflow.STATE_POSTPONED],
                "icon": "ri-user-follow-line",
                "badge": "badge-primary",
            },
        ]
        job_applications = current_org.job_applications_received.values("state").all()
        for category in job_applications_categories:
            category["counter"] = len([ja for ja in job_applications if ja["state"] in category["states"]])
            category[
                "url"
            ] = f"{reverse('apply:list_for_siae')}?{'&'.join([f'states={c}' for c in category['states']])}"

        num_rejected_employee_records = (
            EmployeeRecord.objects.for_siae(current_org).filter(status=Status.REJECTED).count()
        )
        if (
            current_org.can_use_employee_record
            and current_org.convention
            and current_org.convention.is_active
            and not current_org.convention.financial_annexes.filter(
                state__in=SiaeFinancialAnnex.STATES_ACTIVE, end_at__gt=timezone.now()
            ).exists()
        ):
            # We have a SIAE that uses employee record, has an active convention
            # but is missing its financial annex:
            # the ASP data is certainly late, like at every beginning of the year
            # Let's inform our user that they can still use their employee record
            # to avoid support tickets.
            show_previous_year_financial_annex_info = True

    if request.user.is_prescriber:
        try:
            current_org = get_current_org_or_404(request)
        except Http404:
            pass

    if request.user.is_labor_inspector:
        current_org = get_current_institution_or_404(request)
        active_campaigns = EvaluationCampaign.objects.for_institution(current_org).viewable()
        campaign_in_progress = any(campaign.ended_at is None for campaign in active_campaigns)

    context = {
        "current_org": current_org,
        "job_applications_categories": job_applications_categories,
        # FIXME(vperron): I think there's a rising need for a revamped permission system.
        "can_create_siae_antenna": request.user.can_create_siae_antenna(parent_siae=current_org),
        "can_show_financial_annexes": can_show_financial_annexes,
        "can_show_employee_records": can_show_employee_records,
        "can_view_stats_dashboard_widget": request.user.can_view_stats_dashboard_widget(current_org=current_org),
        "can_view_stats_siae_etp": request.user.can_view_stats_siae_etp(current_org=current_org),
        "can_view_stats_siae_hiring": request.user.can_view_stats_siae_hiring(current_org=current_org),
        "can_view_stats_cd": request.user.can_view_stats_cd(current_org=current_org),
        "can_view_stats_pe": request.user.can_view_stats_pe(current_org=current_org),
        "can_view_stats_ddets": request.user.can_view_stats_ddets(current_org=current_org),
        "can_view_stats_dreets": request.user.can_view_stats_dreets(current_org=current_org),
        "can_view_stats_dgefp": request.user.can_view_stats_dgefp(current_org=current_org),
        "can_view_stats_dihal": request.user.can_view_stats_dihal(current_org=current_org),
        "num_rejected_employee_records": num_rejected_employee_records,
        "active_campaigns": active_campaigns,
        "campaign_in_progress": campaign_in_progress,
        "evaluated_siae_notifications": evaluated_siae_notifications,
        "precriber_kind_pe": PrescriberOrganizationKind.PE,
        "precriber_kind_dept": PrescriberOrganizationKind.DEPT,
        "show_previous_year_financial_annex_info": show_previous_year_financial_annex_info,
        "show_dora_banner": (
            any([request.user.is_siae_staff, request.user.is_prescriber])
            and current_org
            and current_org.department in ["08", "60", "91", "974"]
        ),
    }

    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


password_change = login_required(ItouPasswordChangeView.as_view())


@login_required
def edit_user_email(request, template_name="dashboard/edit_user_email.html"):
    if request.user.has_sso_provider:
        return HttpResponseForbidden()
    form = EditUserEmailForm(data=request.POST or None, user_email=request.user.email)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            request.user.email = form.cleaned_data["email"]
            request.user.save()
            request.user.emailaddress_set.all().delete()
        auth.logout(request)
        return HttpResponseRedirect(reverse("account_logout"))

    context = {
        "form": form,
    }

    return render(request, template_name, context)


@login_required
def edit_user_info(request, template_name="dashboard/edit_user_info.html"):
    """
    Edit a user.
    """
    dashboard_url = reverse_lazy("dashboard:index")
    prev_url = get_safe_url(request, "prev_url", fallback_url=dashboard_url)
    if request.user.is_job_seeker:
        form = EditJobSeekerInfoForm(
            instance=request.user,
            editor=request.user,
            data=request.POST or None,
            tally_form_query=f"jobseeker={request.user.pk}",
        )
    else:
        form = EditUserInfoForm(
            instance=request.user,
            data=request.POST or None,
        )
    extra_data = request.user.externaldataimport_set.pe_sources().first()

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Mise à jour de vos informations effectuée !")
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {
        "extra_data": extra_data,
        "form": form,
        "prev_url": prev_url,
    }

    return render(request, template_name, context)


def user_can_edit_job_seeker_info(user, job_application, current_siae_pk=None):
    return (
        # Only when the information is not managed by job seekers themselves
        job_application.has_editable_job_seeker
        and (
            # Same sender (no SQL)
            job_application.sender_id == user.id
            # Member of the SIAE that offers the job application
            or (current_siae_pk and current_siae_pk == job_application.to_siae_id)
            # Member of the authorized prescriber organization who propose the candidate to the job application
            or user.is_prescriber_of_authorized_organization(job_application.sender_prescriber_organization_id)
        )
    )


@login_required
def edit_job_seeker_info(request, job_application_id, template_name="dashboard/edit_job_seeker_info.html"):
    job_application = get_object_or_404(JobApplication.objects.select_related("job_seeker"), pk=job_application_id)
    current_siae_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
    if not user_can_edit_job_seeker_info(request.user, job_application, current_siae_pk):
        raise PermissionDenied

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)
    form = EditJobSeekerInfoForm(
        instance=job_application.job_seeker,
        editor=request.user,
        data=request.POST or None,
        tally_form_query=f"jobapplication={job_application.pk}",
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Les informations du candidat ont été mises à jour.")
        return HttpResponseRedirect(back_url)

    context = {
        "form": form,
        "job_application": job_application,
        "prev_url": back_url,
    }

    return render(request, template_name, context)


@login_required
@require_POST
def switch_siae(request):
    """
    Switch to the dashboard of another SIAE of the same SIREN.
    """
    dashboard_url = reverse_lazy("dashboard:index")

    pk = request.POST["siae_id"]
    queryset = Siae.objects.active_or_in_grace_period().member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)
    request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk

    return HttpResponseRedirect(dashboard_url)


@login_required
@require_POST
def switch_prescriber_organization(request):
    """
    Switch prescriber organization for a user with multiple memberships.
    """
    dashboard_url = reverse_lazy("dashboard:index")

    pk = request.POST["prescriber_organization_id"]
    queryset = PrescriberOrganization.objects
    prescriber_organization = get_object_or_404(queryset, pk=pk)
    request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk

    return HttpResponseRedirect(dashboard_url)


@login_required
@require_POST
def switch_institution(request):
    """
    Switch prescriber organization for a user with multiple memberships.
    """
    dashboard_url = reverse_lazy("dashboard:index")

    pk = request.POST["institution_id"]
    queryset = Institution.objects
    institution = get_object_or_404(queryset, pk=pk)
    request.session[global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY] = institution.pk

    return HttpResponseRedirect(dashboard_url)


@login_required
def edit_user_notifications(request, template_name="dashboard/edit_user_notifications.html"):
    if not request.user.is_siae_staff:
        raise PermissionDenied

    current_siae_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
    siae = get_object_or_404(Siae, pk=current_siae_pk)
    membership = request.user.siaemembership_set.get(siae=siae)
    new_job_app_notification_form = EditNewJobAppEmployersNotificationForm(
        recipient=membership, siae=siae, data=request.POST or None
    )

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)

    if request.method == "POST" and new_job_app_notification_form.is_valid():
        new_job_app_notification_form.save()
        messages.success(request, "Vos préférences ont été modifiées.")
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {
        "new_job_app_notification_form": new_job_app_notification_form,
        "back_url": back_url,
    }

    return render(request, template_name, context)
