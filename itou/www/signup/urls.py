from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    # Job seeker.
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
    # Prescriber.
    path("prescriber/is_pole_emploi", views.prescriber_is_pole_emploi, name="prescriber_is_pole_emploi",),
    path("prescriber/choose_org", views.prescriber_choose_org, name="prescriber_choose_org",),
    path("prescriber/choose_kind", views.prescriber_choose_kind, name="prescriber_choose_kind",),
    path(
        "prescriber/confirm_authorization",
        views.prescriber_confirm_authorization,
        name="prescriber_confirm_authorization",
    ),
    path("prescriber/siret", views.prescriber_siret, name="prescriber_siret",),
    path(
        "prescriber/pole_emploi/safir",
        views.prescriber_pole_emploi_safir_code,
        name="prescriber_pole_emploi_safir_code",
    ),
    path(
        "prescriber/pole_emploi/user",
        views.PrescriberPoleEmploiUserSignupView.as_view(),
        name="prescriber_pole_emploi_user",
    ),
    path("prescriber/user", views.PrescriberUserSignupView.as_view(), name="prescriber_user",),
    # SIAE.
    path("siae/select", views.siae_select, name="siae_select"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.SiaeSignupView.as_view(), name="siae"),
]
