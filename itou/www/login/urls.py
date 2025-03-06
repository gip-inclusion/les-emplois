from django.urls import path

from itou.www.login import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "login"

urlpatterns = [
    path("prescriber", views.PrescriberLoginView.as_view(), name="prescriber"),
    path("employer", views.EmployerLoginView.as_view(), name="employer"),
    path("labor_inspector", views.LaborInspectorLoginView.as_view(), name="labor_inspector"),
    path("job_seeker", views.JobSeekerPreLoginView.as_view(), name="job_seeker"),
    path("itou_staff", views.ItouStaffLoginView.as_view(), name="itou_staff"),
    path("existing/<uuid:user_public_id>", views.ExistingUserLoginView.as_view(), name="existing_user"),
]
