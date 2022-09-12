from django.urls import path, re_path
from django.views.generic import TemplateView

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    # Job seeker.
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
    path("job_seeker/nir", views.job_seeker_nir, name="job_seeker_nir"),
    path("job_seeker/situation", views.job_seeker_situation, name="job_seeker_situation"),
    path(
        "job_seeker/situation_not_eligible",
        TemplateView.as_view(template_name="signup/job_seeker_situation_not_eligible.html"),
        name="job_seeker_situation_not_eligible",
    ),
    path(
        "facilitator/search",
        views.facilitator_search,
        name="facilitator_search",
    ),
    path(
        "facilitator/signup",
        views.FacilitatorSignupView.as_view(),
        name="facilitator_signup",
    ),
    # Prescriber.
    path(
        "prescriber/check_already_exists",
        views.prescriber_check_already_exists,
        name="prescriber_check_already_exists",
    ),
    path(
        "prescriber/request_invitation/<int:membership_id>",
        views.prescriber_request_invitation,
        name="prescriber_request_invitation",
    ),
    re_path(
        r"^prescriber/choose_org/(?P<siret>\d{14})?$",
        views.prescriber_choose_org,
        name="prescriber_choose_org",
    ),
    path(
        "prescriber/choose_kind",
        views.prescriber_choose_kind,
        name="prescriber_choose_kind",
    ),
    path(
        "prescriber/confirm_authorization",
        views.prescriber_confirm_authorization,
        name="prescriber_confirm_authorization",
    ),
    path(
        "prescriber/pole_emploi/safir",
        views.prescriber_pole_emploi_safir_code,
        name="prescriber_pole_emploi_safir_code",
    ),
    path(
        "prescriber/pole_emploi/check_email",
        views.prescriber_check_pe_email,
        name="prescriber_check_pe_email",
    ),
    path(
        "prescriber/pole_emploi/user",
        views.prescriber_pole_emploi_user,
        name="prescriber_pole_emploi_user",
    ),
    path(
        "prescriber/user",
        views.prescriber_user,
        name="prescriber_user",
    ),
    path(
        "prescriber/join_org",
        views.prescriber_join_org,
        name="prescriber_join_org",
    ),
    # SIAE.
    path("siae/select", views.siae_select, name="siae_select"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.siae_user, name="siae_user"),
    path("siae/join/<str:encoded_siae_id>/<str:token>", views.siae_join, name="siae_join"),
]
