from django.urls import path, re_path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    path("", views.ChooseUserKindSignupView.as_view(), name="choose_user_kind"),
    # Job seeker.
    path(
        "job_seeker/start",
        views.JobSeekerStartSignupView.as_view(),
        name="job_seeker_start",
    ),
    path(
        "job_seeker/situation",
        views.JobSeekerSituationSignupView.as_view(),
        name="job_seeker_situation",
    ),
    path(
        "job_seeker/criteria",
        views.JobSeekerCriteriaSignupView.as_view(),
        name="job_seeker_criteria",
    ),
    path("job_seeker", views.job_seeker_signup_info, name="job_seeker"),
    path(
        "job_seeker/credentials",
        views.JobSeekerCredentialsSignupView.as_view(),
        name="job_seeker_credentials",
    ),
    path(
        "facilitator/search",
        views.facilitator_search,
        name="facilitator_search",
    ),
    path(
        "facilitator/user",
        views.FacilitatorUserView.as_view(),
        name="facilitator_user",
    ),
    path(
        "facilitator/join",
        views.FacilitatorJoinView.as_view(),
        name="facilitator_join",
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
    path("siae/select", views.company_select, name="company_select"),
    path("siae/<int:company_id>/<str:token>", views.CompanyUserView.as_view(), name="employer"),
    path("siae/join/<int:company_id>/<str:token>", views.CompanyJoinView.as_view(), name="company_join"),
]
