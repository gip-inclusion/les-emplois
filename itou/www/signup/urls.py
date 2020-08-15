from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    # Prescriber/orienter NEW.
    path("prescriber", views.prescriber_entry_point, name="prescriber_entry_point"),
    path(
        "prescriber/poleemploi/safir",
        views.prescriber_pole_emploi_safir_code,
        name="prescriber_pole_emploi_safir_code",
    ),
    path(
        "prescriber/poleemploi/user",
        views.PrescriberPoleEmploiUserSignupView.as_view(),
        name="prescriber_pole_emploi_user",
    ),
    # Prescriber/orienter OLD.
    path("select_prescriber_type", views.select_prescriber_type, name="select_prescriber_type"),
    path("prescriber/orienter", views.OrienterPrescriberView.as_view(), name="prescriber_orienter"),
    path("prescriber/poleemploi", views.PoleEmploiPrescriberView.as_view(), name="prescriber_poleemploi"),
    path("prescriber/authorized", views.AuthorizedPrescriberView.as_view(), name="prescriber_authorized"),
    # SIAE.
    path("select_siae", views.select_siae, name="select_siae"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.SiaeSignupView.as_view(), name="siae"),
    path("siae", views.SiaeSignupView.as_view(), name="siae"),
    # Job seeker.
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
]
