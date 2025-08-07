import enum

from allauth.account.internal.flows.email_verification import send_verification_email_to_address
from allauth.account.models import EmailAddress
from allauth.account.views import PasswordChangeView
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.cache import caches
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from rest_framework.authtoken.models import Token

from itou.api.token_auth.views import TOKEN_ID_STR
from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.institutions.enums import InstitutionKind
from itou.job_applications.enums import JobApplicationState
from itou.metabase.models import DatumKey
from itou.siae_evaluations.models import EvaluatedSiae, EvaluationCampaign
from itou.users.enums import MATOMO_ACCOUNT_TYPE, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.utils import can_edit_personal_information
from itou.utils.urls import get_safe_url
from itou.www.dashboard.forms import (
    EditJobSeekerInfoForm,
    EditUserEmailForm,
    EditUserInfoForm,
    EditUserNotificationForm,
)
from itou.www.gps.views import is_allowed_to_use_gps, show_gps_as_a_nav_entry
from itou.www.search.forms import SiaeSearchForm
from itou.www.stats import utils as stats_utils
from itou.www.stats.utils import get_stats_for_institution


class DashboardStatsLayoutKind(enum.StrEnum):
    EMPLOYER = "employer"
    PRESCRIBER = "prescriber"
    PRESCRIBER_FT = "prescriber_ft"
    PRESCRIBER_DEPT = "prescriber_dept"
    SD_IAE = "sd_iae"
    DGEFP = "dgefp"

    LEGACY = "legacy"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


def _employer_dashboard_context(request):
    current_org = get_current_company_or_404(request)
    states_to_process = [JobApplicationState.NEW, JobApplicationState.PROCESSING]
    if current_org.can_have_prior_action:
        states_to_process.append(JobApplicationState.PRIOR_TO_HIRE)

    job_applications_categories = [
        {
            "name": "À traiter",
            "states": states_to_process,
            "icon": "ri-notification-4-line",
            "badge": "bg-info-lighter",
        },
        {
            "name": "En attente",
            "states": [JobApplicationState.POSTPONED],
            "icon": "ri-time-line",
            "badge": "bg-info-lighter",
        },
    ]
    job_applications = current_org.job_applications_received.filter(archived_at=None).values("state").all()
    for category in job_applications_categories:
        category["counter"] = len([ja for ja in job_applications if ja["state"] in category["states"]])
        category["url"] = f"{reverse('apply:list_for_siae')}?{'&'.join([f'states={c}' for c in category['states']])}"

    return {
        "active_campaigns": (
            EvaluatedSiae.objects.for_company(current_org)
            .in_progress()
            .select_related("evaluation_campaign")
            .prefetch_related(
                "evaluated_job_applications",
                "evaluated_job_applications__evaluated_administrative_criteria",
            )
        ),
        "can_show_employee_records": current_org.can_use_employee_record,
        "can_show_financial_annexes": current_org.convention_can_be_accessed_by(request.user),
        "evaluated_siae_notifications": (
            EvaluatedSiae.objects.for_company(current_org)
            .exclude(notified_at=None)
            .viewable()
            .select_related("evaluation_campaign")
        ),
        "job_applications_categories": job_applications_categories,
        "num_rejected_employee_records": (
            EmployeeRecord.objects.for_company(current_org).filter(status=Status.REJECTED).count()
        ),
        "siae_suspension_text_with_dates": (
            current_org.get_active_suspension_text_with_dates()
            # Otherwise they cannot be suspended
            if current_org.is_subject_to_eligibility_rules
            else None
        ),
        "states_to_process": states_to_process,
    }


def dashboard(request, template_name="dashboard/dashboard.html"):
    context = {
        "active_geiq_campaign": None,
        "active_campaigns": [],
        "closed_campaigns": [],
        "job_applications_categories": [],
        "can_show_financial_annexes": False,
        "can_show_employee_records": False,
        "can_view_gps_card": is_allowed_to_use_gps(request) and not show_gps_as_a_nav_entry(request),
        "can_view_stats_dashboard_widget": stats_utils.can_view_stats_dashboard_widget(request),
        "num_rejected_employee_records": 0,
        "pending_prolongation_requests": None,
        "evaluated_siae_notifications": EvaluatedSiae.objects.none(),
        "siae_suspension_text_with_dates": None,
        "siae_search_form": SiaeSearchForm(),
        "stalled_job_seekers_count": None,
    }

    if request.user.is_employer:
        context.update(_employer_dashboard_context(request))
    elif request.user.is_prescriber:
        if current_org := request.current_organization:
            context["stalled_job_seekers_count"] = User.objects.linked_job_seeker_ids(
                request.user,
                request.current_organization,
                stalled=True,
            ).count()
            if current_org.is_authorized:
                context["pending_prolongation_requests"] = ProlongationRequest.objects.filter(
                    prescriber_organization=current_org,
                    status=ProlongationRequestStatus.PENDING,
                ).count()
    elif request.user.is_labor_inspector:
        current_org = get_current_institution_or_404(request)
        six_months_ago = timezone.now() - timezone.timedelta(days=182)
        for campaign in EvaluationCampaign.objects.for_institution(current_org).viewable():
            if campaign.ended_at is None or campaign.ended_at >= six_months_ago:
                context["active_campaigns"].append(campaign)
            else:
                context["closed_campaigns"].append(campaign)
    elif request.user.is_job_seeker:
        # Force job seekers to complete their profile.
        required_attributes = ["title", "first_name", "last_name", "address_line_1", "post_code", "city"]
        for attr in required_attributes:
            if not getattr(request.user, attr):
                return HttpResponseRedirect(reverse("dashboard:edit_user_info"))

        iae_eligibility_diagnosis = EligibilityDiagnosis.objects.last_for_job_seeker(request.user)
        geiq_eligibility_diagnosis = (
            GEIQEligibilityDiagnosis.objects.diagnoses_for(
                job_seeker=request.user,
                for_geiq=None,
                for_job_seeker=True,
            )
            .prefetch_related("selected_administrative_criteria__administrative_criteria")
            .first()
        )

        context |= {
            "iae_eligibility_diagnosis": iae_eligibility_diagnosis,
            "geiq_eligibility_diagnosis": geiq_eligibility_diagnosis,
        }
    return render(request, template_name, context)


def dashboard_stats(request, template_name="dashboard/dashboard_stats.html"):
    if not stats_utils.can_view_stats_dashboard_widget(request):
        return HttpResponseForbidden()

    context = {
        "layout_kind": DashboardStatsLayoutKind.LEGACY,
        "DashboardStatsLayoutKind": DashboardStatsLayoutKind,
        "stats_kpi": None,
    }

    if request.user.is_employer:
        context["siae_suspension_text_with_dates"] = (
            request.current_organization.get_active_suspension_text_with_dates()
            # Otherwise they cannot be suspended
            if request.current_organization.is_subject_to_eligibility_rules
            else None
        )
        if stats_utils.can_view_stats_siae(request):
            context.update(
                {
                    "layout_kind": DashboardStatsLayoutKind.EMPLOYER,
                    "can_view_stats_siae_etp": stats_utils.can_view_stats_siae_etp(request),
                }
            )
    elif request.user.is_prescriber:
        if stats_utils.can_view_stats_cd(request):
            context["layout_kind"] = DashboardStatsLayoutKind.PRESCRIBER_DEPT
        elif stats_utils.can_view_stats_ft(request):
            context["layout_kind"] = DashboardStatsLayoutKind.PRESCRIBER_FT
        elif stats_utils.can_view_stats_ph(request):
            context.update(
                {
                    "layout_kind": DashboardStatsLayoutKind.PRESCRIBER,
                    "can_view_stats_ph_whitelisted": stats_utils.can_view_stats_ph_whitelisted(request),
                }
            )
            context["layout_kind"] = DashboardStatsLayoutKind.PRESCRIBER
    elif request.user.is_labor_inspector:
        if request.current_organization.kind in [
            InstitutionKind.DGEFP_IAE,
            InstitutionKind.DREETS_IAE,
            InstitutionKind.DDETS_IAE,
        ]:
            context["stats_kpi"] = {
                DatumKey.FLUX_IAE_DATA_UPDATED_AT: caches["stats"].get(DatumKey.FLUX_IAE_DATA_UPDATED_AT),
                DatumKey.JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS: get_stats_for_institution(
                    request.current_organization, DatumKey.JOB_SEEKER_STILL_SEEKING_AFTER_30_DAYS
                ),
                DatumKey.JOB_APPLICATION_WITH_HIRING_DIFFICULTY: get_stats_for_institution(
                    request.current_organization, DatumKey.JOB_APPLICATION_WITH_HIRING_DIFFICULTY
                ),
                DatumKey.RATE_OF_AUTO_PRESCRIPTION: get_stats_for_institution(
                    request.current_organization,
                    DatumKey.RATE_OF_AUTO_PRESCRIPTION,
                    is_percentage=True,
                ),
            }
        if stats_utils.can_view_stats_dgefp_iae(request):
            context["layout_kind"] = DashboardStatsLayoutKind.DGEFP
        elif stats_utils.can_view_stats_ddets_iae(request) or stats_utils.can_view_stats_dreets_iae(request):
            context["layout_kind"] = DashboardStatsLayoutKind.SD_IAE

    if context["layout_kind"] is DashboardStatsLayoutKind.LEGACY:
        context.update(
            {
                "can_view_stats_ddets_log": stats_utils.can_view_stats_ddets_log(request),
                "can_view_stats_dihal": stats_utils.can_view_stats_dihal(request),
                "can_view_stats_drihl": stats_utils.can_view_stats_drihl(request),
                "can_view_stats_iae_network": stats_utils.can_view_stats_iae_network(request),
                "can_view_stats_convergence": stats_utils.can_view_stats_convergence(request),
            }
        )
        context["has_view_stats_items"] = any(v for k, v in context.items() if k.startswith("can_view_stats_"))

    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


def edit_user_email(request, template_name="dashboard/edit_user_email.html"):
    if request.user.has_sso_provider:
        return HttpResponseForbidden()
    form = EditUserEmailForm(request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        address, _ = EmailAddress.objects.get_or_create(user=request.user, email=form.cleaned_data["email"])
        # Do no update the user email : django allauth will do it when confirming the email.
        send_verification_email_to_address(request, address=address)
        return HttpResponseRedirect(reverse("dashboard:index"))

    return render(request, template_name, {"form": form})


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
            back_url=request.get_full_path(),
        )
    else:
        form = EditUserInfoForm(
            instance=request.user,
            data=request.POST or None,
        )
    extra_data = request.user.externaldataimport_set.pe_sources().first()

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Les informations de votre profil ont bien été mises à jour.", extra_tags="toast")
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {
        "extra_data": extra_data,
        "form": form,
        "prev_url": prev_url,
    }

    return render(request, template_name, context)


def edit_job_seeker_info(request, job_seeker_public_id, template_name="dashboard/edit_job_seeker_info.html"):
    job_seeker = get_object_or_404(
        User.objects.filter(kind=UserKind.JOB_SEEKER).select_related("jobseeker_profile"),
        public_id=job_seeker_public_id,
    )
    if not can_edit_personal_information(request, job_seeker):
        raise PermissionDenied

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)
    form = EditJobSeekerInfoForm(
        instance=job_seeker,
        editor=request.user,
        data=request.POST or None,
        back_url=request.get_full_path(),
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Les informations du candidat ont bien été mises à jour.", extra_tags="toast")
        return HttpResponseRedirect(back_url)

    context = {
        "form": form,
        "job_seeker": job_seeker,
        "prev_url": back_url,
        "matomo_custom_title": "Informations personnelles du candidat",
    }

    return render(request, template_name, context)


@require_POST
def switch_organization(request):
    try:
        pk = int(request.POST["organization_id"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest(b"organization_id key is missing")

    if request.user.kind not in {
        UserKind.EMPLOYER,
        UserKind.PRESCRIBER,
        UserKind.LABOR_INSPECTOR,
    } or pk not in {organization.pk for organization in request.organizations}:
        raise Http404()

    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = pk
    return HttpResponseRedirect(reverse("dashboard:index"))


def edit_user_notifications(request, template_name="dashboard/edit_user_notifications.html"):
    if request.user.is_staff:
        raise Http404("L'utilisateur admin ne peut gérer ses notifications.")
    elif request.user.is_labor_inspector:
        raise Http404("Ce compte utilisateur ne peut gérer ses notifications.")
    elif request.user.is_job_seeker:
        notification_form = EditUserNotificationForm(user=request.user, structure=None, data=request.POST or None)
    else:
        notification_form = EditUserNotificationForm(
            user=request.user, structure=request.current_organization, data=request.POST or None
        )

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)

    if request.method == "POST" and notification_form.is_valid():
        notification_form.save()
        messages.success(request, "Vos préférences de notifications ont été modifiées.", extra_tags="toast")
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {
        "notification_form": notification_form,
        "back_url": back_url,
    }

    return render(request, template_name, context)


def api_token(request, template_name="dashboard/api_token.html"):
    if not (request.user.is_employer and request.is_current_organization_admin):
        raise PermissionDenied

    if request.method == "POST":
        token, _created = Token.objects.get_or_create(user=request.user)
    else:
        token = Token.objects.filter(user=request.user).first()  # May be None if no token

    context = {
        "back_url": reverse("dashboard:index"),
        "login_string": TOKEN_ID_STR,
        "token": token,
        "companies": request.user.companymembership_set.active_admin().values(
            name=F("company__name"), uid=F("company__uid")
        ),
    }

    return render(request, template_name, context)


class AccountMigrationView(TemplateView):
    template_name = "account/activate_pro_connect_account.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.kind not in MATOMO_ACCOUNT_TYPE:
            return HttpResponseRedirect(reverse("dashboard:index"))
        return super().dispatch(request, *args, **kwargs)

    def _get_params(self):
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
        params = self._get_params()
        pro_connect_url = reverse("pro_connect:authorize", query=params) if settings.PRO_CONNECT_BASE_URL else None

        extra_context = {
            "pro_connect_url": pro_connect_url,
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[self.request.user.kind],
        }
        return context | extra_context
