from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    # Prescriber.
    path(
        "prescriber/who_are_you/step1",
        views.prescriber_intro_step_pole_emploi,
        name="prescriber_intro_step_pole_emploi",
    ),
    path("prescriber/who_are_you/step2", views.prescriber_intro_step_org, name="prescriber_intro_step_org",),
    path("prescriber/who_are_you/step3", views.prescriber_intro_step_kind, name="prescriber_intro_step_kind",),
    path(
        "prescriber/who_are_you/step4",
        views.prescriber_intro_step_authorization,
        name="prescriber_intro_step_authorization",
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
    path("select_siae", views.select_siae, name="select_siae"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.SiaeSignupView.as_view(), name="siae"),
    path("siae", views.SiaeSignupView.as_view(), name="siae"),
    # Job seeker.
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
]
