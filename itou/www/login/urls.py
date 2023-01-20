from django.urls import path

from itou.www.login import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "login"

urlpatterns = [
    path("prescriber", views.PrescriberLoginView.as_view(), name="prescriber"),
    path("siae_staff", views.SiaeStaffLoginView.as_view(), name="siae_staff"),
    path("labor_inspector", views.LaborInspectorLoginView.as_view(), name="labor_inspector"),
    path("job_seeker", views.JobSeekerLoginView.as_view(), name="job_seeker"),
    path(
        "activate_prescriber_account",
        views.PrescriberAccountMigrationView.as_view(),
        name="activate_prescriber_account",
    ),
    path(
        "activate_siae_staff_account",
        views.SiaeStaffAccountMigrationView.as_view(),
        name="activate_siae_staff_account",
    ),
]
