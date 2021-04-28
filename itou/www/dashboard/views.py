from allauth.account.views import LogoutView, PasswordChangeView
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.tokens import resume_signer
from itou.utils.urls import get_safe_url
from itou.www.dashboard.forms import EditNewJobAppEmployersNotificationForm, EditUserEmailForm, EditUserInfoForm


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):
    can_show_financial_annexes = False
    can_show_employee_records = False
    job_applications_categories = []

    if request.user.is_siae_staff:
        siae = get_current_siae_or_404(request)
        can_show_financial_annexes = siae.convention_can_be_accessed_by(request.user)
        can_show_employee_records = siae.can_use_employee_record
        job_applications_categories = [
            {
                "name": "Candidatures à traiter",
                "states": [JobApplicationWorkflow.STATE_NEW, JobApplicationWorkflow.STATE_PROCESSING],
                "icon": "user-plus",
                "badge": "badge-danger",
            },
            {
                "name": "Candidatures acceptées ou mises en liste d'attente",
                "states": [JobApplicationWorkflow.STATE_ACCEPTED, JobApplicationWorkflow.STATE_POSTPONED],
                "icon": "user-check",
                "badge": "badge-secondary",
            },
            {
                "name": "Candidatures refusées/annulées",
                "states": [
                    JobApplicationWorkflow.STATE_REFUSED,
                    JobApplicationWorkflow.STATE_CANCELLED,
                    JobApplicationWorkflow.STATE_OBSOLETE,
                ],
                "icon": "user-x",
                "badge": "badge-secondary",
            },
        ]
        job_applications = siae.job_applications_received.values("state").all()
        for category in job_applications_categories:
            category["counter"] = len([ja for ja in job_applications if ja["state"] in category["states"]])
            category[
                "url"
            ] = f"{reverse('apply:list_for_siae')}?{'&'.join([f'states={c}' for c in category['states']])}"

    context = {
        "lemarche_regions": settings.LEMARCHE_OPEN_REGIONS,
        "job_applications_categories": job_applications_categories,
        "can_show_financial_annexes": can_show_financial_annexes,
        "can_show_employee_records": can_show_employee_records,
    }

    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


password_change = login_required(ItouPasswordChangeView.as_view())


class ItouLogoutView(LogoutView):
    def post(self, *args, **kwargs):
        """
        We overload this method so that we can process the PEAMU callback
        when the user logs out.
        Original code:
        https://github.com/pennersr/django-allauth/blob/master/allauth/account/views.py#L775
        """
        peamu_id_token = self.request.user.peamu_id_token
        ajax_response = super().post(*args, **kwargs)
        if peamu_id_token:
            hp_url = self.request.build_absolute_uri("/")
            params = {"id_token_hint": peamu_id_token, "redirect_uri": hp_url}
            peamu_logout_url = f"{settings.PEAMU_AUTH_BASE_URL}/compte/deconnexion?{urlencode(params)}"
            return HttpResponseRedirect(peamu_logout_url)
        else:
            return ajax_response


logout = login_required(ItouLogoutView.as_view())


@login_required
def edit_user_email(request, template_name="dashboard/edit_user_email.html"):
    form = EditUserEmailForm(data=request.POST or None, user_email=request.user.email)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            request.user.email = form.cleaned_data["email"]
            request.user.save()
            request.user.emailaddress_set.first().delete()
        auth.logout(request)
        return HttpResponseRedirect("/")

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
    form = EditUserInfoForm(instance=request.user, data=request.POST or None)
    extra_data = request.user.externaldataimport_set.pe_sources().first()
    job_seeker_signed_pk = resume_signer.sign(request.user.pk)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Mise à jour de vos informations effectuée !")
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {
        "extra_data": extra_data,
        "form": form,
        "job_seeker_signed_pk": job_seeker_signed_pk,
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
    current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
    if not user_can_edit_job_seeker_info(request.user, job_application, current_siae_pk):
        raise PermissionDenied

    dashboard_url = reverse_lazy("dashboard:index")
    back_url = get_safe_url(request, "back_url", fallback_url=dashboard_url)
    form = EditUserInfoForm(instance=job_application.job_seeker, data=request.POST or None)

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
    request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk

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
    request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk

    return HttpResponseRedirect(dashboard_url)


@login_required
def edit_user_preferences(request, template_name="dashboard/edit_user_preferences.html"):
    if not request.user.is_siae_staff:
        raise PermissionDenied

    current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
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
