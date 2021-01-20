from django.urls import path

from itou.www.dashboard import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("edit_user_email", views.edit_user_email, name="edit_user_email"),
    path("edit_user_info", views.edit_user_info, name="edit_user_info"),
    path("edit_job_seeker_info/<uuid:job_application_id>", views.edit_job_seeker_info, name="edit_job_seeker_info"),
    path("switch_siae", views.switch_siae, name="switch_siae"),
    path(
        "switch_prescriber_organization", views.switch_prescriber_organization, name="switch_prescriber_organization"
    ),
]
