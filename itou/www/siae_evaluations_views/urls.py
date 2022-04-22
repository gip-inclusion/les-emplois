from django.urls import path

from itou.www.siae_evaluations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siae_evaluations_views"

urlpatterns = [
    path("samples_selection", views.samples_selection, name="samples_selection"),
    path("siae_job_applications_list", views.siae_job_applications_list, name="siae_job_applications_list"),
    path(
        "siae_select_criteria/<int:evaluated_job_application_pk>/",
        views.siae_select_criteria,
        name="siae_select_criteria",
    ),
]
