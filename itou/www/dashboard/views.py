from allauth.account.views import PasswordChangeView
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from rest_framework.authtoken.models import Token

from itou.api.token_auth.views import TOKEN_ID_STR
from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.institutions.models import Institution
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.openid_connect.inclusion_connect import constants as ic_constants
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import EvaluatedSiae, EvaluationCampaign
from itou.users.enums import MATOMO_ACCOUNT_TYPE, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.urls import add_url_params, get_absolute_url, get_safe_url
from itou.www.dashboard.forms import (
    EditJobSeekerInfoForm,
    EditNewJobAppEmployersNotificationForm,
    EditUserEmailForm,
    EditUserInfoForm,
)
from itou.www.stats import utils as stats_utils


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):
    can_show_financial_annexes = False
    can_show_employee_records = False
    job_applications_categories = []
    num_rejected_employee_records = 0
    pending_prolongation_requests = None
    active_campaigns = []
    closed_campaigns = []
    evaluated_siae_notifications = EvaluatedSiae.objects.none()
    siae_suspension_text_with_dates = None

    # `current_org` can be a Siae, a PrescriberOrganization or an Institution.
    current_org = None

    if request.user.is_employer:
        current_org = get_current_company_or_404(request)
        can_show_financial_annexes = current_org.convention_can_be_accessed_by(request.user)
        can_show_employee_records = current_org.can_use_employee_record
        active_campaigns = (
            EvaluatedSiae.objects.for_company(current_org)
            .in_progress()
            .select_related("evaluation_campaign")
            .prefetch_related(
                "evaluated_job_applications",
                "evaluated_job_applications__evaluated_administrative_criteria",
            )
        )
        evaluated_siae_notifications = (
            EvaluatedSiae.objects.for_company(current_org)
            .exclude(notified_at=None)
            .filter(
                Q(evaluation_campaign__ended_at=None)
                | Q(evaluation_campaign__ended_at__gte=timezone.now() - CAMPAIGN_VIEWABLE_DURATION)
            )
            .select_related("evaluation_campaign")
        )

        states_to_process = [JobApplicationWorkflow.STATE_NEW, JobApplicationWorkflow.STATE_PROCESSING]
        if current_org.can_have_prior_action:
            states_to_process.append(JobApplicationWorkflow.STATE_PRIOR_TO_HIRE)

        job_applications_categories = [
            {
                "name": "À traiter",
                "states": states_to_process,
                "icon": "ri-notification-4-line",
                "badge": "bg-info-lighter",
            },
            {
                "name": "En attente",
                "states": [JobApplicationWorkflow.STATE_POSTPONED],
                "icon": "ri-time-line",
                "badge": "bg-info-lighter",
            },
        ]
        job_applications = current_org.job_applications_received.values("state").all()
        for category in job_applications_categories:
            category["counter"] = len([ja for ja in job_applications if ja["state"] in category["states"]])
            category[
                "url"
            ] = f"{reverse('apply:list_for_siae')}?{'&'.join([f'states={c}' for c in category['states']])}"

        num_rejected_employee_records = (
            EmployeeRecord.objects.for_company(current_org).filter(status=Status.REJECTED).count()
        )
        if current_org.is_subject_to_eligibility_rules:
            # Otherwise they cannot be suspended
            siae_suspension_text_with_dates = current_org.get_active_suspension_text_with_dates()

    if request.user.is_prescriber:
        try:
            current_org = get_current_org_or_404(request)
        except Http404:
            # User is a prescriber without organization (orienter)
            if request.user.is_prescriber_with_org:
                # Prescriber can be removed from an organization while logged-in
                # but can still be member of other prescriber organizations.
                # in this case, we must not display any message
                pass
            elif request.user.email.endswith("pole-emploi.fr"):
                messages.info(
                    request,
                    mark_safe(
                        f"Votre compte utilisateur n’est rattaché à aucune agence Pôle emploi, "
                        f"par conséquent vous ne pouvez pas bénéficier du statut de prescripteur habilité.<br>"
                        f"Rejoignez l’espace de travail de votre agence Pôle emploi "
                        f"<a href='{reverse('signup:prescriber_pole_emploi_safir_code')}'>en cliquant ici</a>."
                    ),
                )
            else:
                messages.info(
                    request,
                    mark_safe(
                        f"Votre compte utilisateur n’est rattaché à aucune organisation.<br>"
                        f"Si vous souhaitez rejoindre le tableau de bord d’une organisation, "
                        f"vous pouvez demander une invitation à vos collègues ou suivre la "
                        f"<a href='{reverse('signup:prescriber_check_already_exists')}'>procédure d’inscription</a> "
                        f"si votre organisation n’est pas encore enregistrée sur le site.<br>"
                        f"Si vous souhaitez continuer à utiliser le service sans être rattaché(e) à une organisation, "
                        f"vous pouvez ignorer ce message."
                    ),
                )
        else:
            if current_org.is_authorized:
                pending_prolongation_requests = ProlongationRequest.objects.filter(
                    prescriber_organization=current_org,
                    status=ProlongationRequestStatus.PENDING,
                ).count()

    if request.user.is_labor_inspector:
        current_org = get_current_institution_or_404(request)
        for campaign in EvaluationCampaign.objects.for_institution(current_org).viewable():
            if campaign.ended_at is None:
                active_campaigns.append(campaign)
            else:
                closed_campaigns.append(campaign)

    context = {
        "job_applications_categories": job_applications_categories,
        # FIXME(vperron): I think there's a rising need for a revamped permission system.
        "can_create_siae_antenna": request.user.can_create_siae_antenna(parent_siae=current_org),
        "can_show_financial_annexes": can_show_financial_annexes,
        "can_show_employee_records": can_show_employee_records,
        "can_view_stats_dashboard_widget": stats_utils.can_view_stats_dashboard_widget(request),
        "can_view_stats_siae": stats_utils.can_view_stats_siae(request),
        "can_view_stats_siae_aci": stats_utils.can_view_stats_siae_aci(request),
        "can_view_stats_siae_etp": stats_utils.can_view_stats_siae_etp(request),
        "can_view_stats_cd": stats_utils.can_view_stats_cd(request),
        "can_view_stats_pe": stats_utils.can_view_stats_pe(request),
        "can_view_stats_ddets_iae": stats_utils.can_view_stats_ddets_iae(request),
        "can_view_stats_ddets_log": stats_utils.can_view_stats_ddets_log(request),
        "can_view_stats_dreets_iae": stats_utils.can_view_stats_dreets_iae(request),
        "can_view_stats_dgefp": stats_utils.can_view_stats_dgefp(request),
        "can_view_stats_dihal": stats_utils.can_view_stats_dihal(request),
        "can_view_stats_drihl": stats_utils.can_view_stats_drihl(request),
        "can_view_stats_iae_network": stats_utils.can_view_stats_iae_network(request),
        "num_rejected_employee_records": num_rejected_employee_records,
        "pending_prolongation_requests": pending_prolongation_requests,
        "active_campaigns": active_campaigns,
        "closed_campaigns": closed_campaigns,
        "evaluated_siae_notifications": evaluated_siae_notifications,
        "siae_suspension_text_with_dates": siae_suspension_text_with_dates,
        "precriber_kind_pe": PrescriberOrganizationKind.PE,
        "precriber_kind_dept": PrescriberOrganizationKind.DEPT,
        "show_dora_banner": (
            any([request.user.is_employer, request.user.is_prescriber])
            and current_org
            and current_org.department in ["91", "26", "74", "30"]
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

    ic_account_url = None
    if request.user.identity_provider == IdentityProvider.INCLUSION_CONNECT and settings.INCLUSION_CONNECT_BASE_URL:
        # SSO users do not have access to edit_user_email dedicated view:
        # this field allows them to discover their dedicated process
        ic_login_params = {
            "next_url": request.build_absolute_uri(),
            "user_kind": request.user.kind,
        }
        inclusion_connect_url = (
            f"{get_absolute_url(reverse('inclusion_connect:authorize'))}?{urlencode(ic_login_params)}"
        )
        params = {
            "referrer": ic_constants.INCLUSION_CONNECT_CLIENT_ID,
            "referrer_uri": inclusion_connect_url,
        }
        ic_account_url = f"{ic_constants.INCLUSION_CONNECT_ACCOUNT_URL}?{urlencode(params)}"

    context = {
        "extra_data": extra_data,
        "form": form,
        "prev_url": prev_url,
        "ic_account_url": ic_account_url,
    }

    return render(request, template_name, context)


@login_required
def edit_job_seeker_info(
    request, job_application_id=None, job_seeker_pk=None, template_name="dashboard/edit_job_seeker_info.html"
):
    if job_application_id:
        # TODO(xafer): remove support for this url pattern in a week
        job_application = get_object_or_404(JobApplication.objects.select_related("job_seeker"), pk=job_application_id)
        job_seeker = job_application.job_seeker
        tally_form_query = f"jobapplication={job_application.pk}"
    elif job_seeker_pk:
        job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), pk=job_seeker_pk)
        from_application_uuid = request.GET.get("from_application")
        tally_form_query = from_application_uuid and f"jobapplication={from_application_uuid}"
    else:
        raise RuntimeError("We need either job_application_id or job_seeker_pk here")
    if not request.user.can_edit_personal_information(job_seeker):
        raise PermissionDenied

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)
    form = EditJobSeekerInfoForm(
        instance=job_seeker,
        editor=request.user,
        data=request.POST or None,
        tally_form_query=tally_form_query,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Les informations du candidat ont été mises à jour.")
        return HttpResponseRedirect(back_url)

    context = {
        "form": form,
        "job_seeker": job_seeker,
        "prev_url": back_url,
        "matomo_custom_title": "Informations personnelles du candidat",
    }

    return render(request, template_name, context)


@login_required
@require_POST
def switch_organization(request):
    pk = request.POST["organization_id"]
    match request.user.kind:
        case UserKind.EMPLOYER:
            queryset = Company.objects.active_or_in_grace_period().member_required(request.user)
        case UserKind.PRESCRIBER:
            queryset = PrescriberOrganization.objects.member_required(request.user)
        case UserKind.LABOR_INSPECTOR:
            queryset = Institution.objects.member_required(request.user)
        case _:
            raise Http404()

    organization = get_object_or_404(queryset, pk=pk)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = organization.pk
    return HttpResponseRedirect(reverse("dashboard:index"))


@login_required
def edit_user_notifications(request, template_name="dashboard/edit_user_notifications.html"):
    if not request.user.is_employer:
        raise PermissionDenied

    current_company_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
    company = get_object_or_404(Company, pk=current_company_pk)
    membership = request.user.companymembership_set.get(company=company)
    new_job_app_notification_form = EditNewJobAppEmployersNotificationForm(
        recipient=membership, company=company, data=request.POST or None
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


@login_required
def api_token(request, template_name="dashboard/api_token.html"):
    if not (request.user.is_employer and request.is_current_organization_admin):
        raise PermissionDenied

    if request.method == "POST":
        token, _created = Token.objects.get_or_create(user=request.user)
    else:
        token = Token.objects.filter(user=request.user).first()  # May be None if no token

    context = {
        "login_string": TOKEN_ID_STR,
        "token": token,
        "siaes_names": request.user.companymembership_set.active_admin().values_list("company__name", flat=True),
    }

    return render(request, template_name, context)


class AccountMigrationView(LoginRequiredMixin, TemplateView):
    template_name = "account/activate_inclusion_connect_account.html"

    def _get_inclusion_connect_base_params(self):
        params = {
            "user_kind": self.request.user.kind,
            "previous_url": self.request.get_full_path(),
            "user_email": self.request.user.email,
        }
        next = get_safe_url(self.request, REDIRECT_FIELD_NAME)
        if next:
            params["next_url"] = next
        return params

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self._get_inclusion_connect_base_params()
        inclusion_connect_url = add_url_params(reverse("inclusion_connect:activate_account"), params)
        extra_context = {
            "inclusion_connect_url": inclusion_connect_url,
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[self.request.user.kind],
        }
        return context | extra_context
