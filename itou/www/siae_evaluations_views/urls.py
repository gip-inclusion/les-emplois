from django.urls import path

from itou.www.siae_evaluations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siae_evaluations_views"

urlpatterns = [
    path("samples_selection", views.samples_selection, name="samples_selection"),
    path(
        "institution_evaluated_siae_list/<int:evaluation_campaign_pk>/",
        views.institution_evaluated_siae_list,
        name="institution_evaluated_siae_list",
    ),
    path(
        "institution_evaluated_siae_detail/<int:evaluated_siae_pk>/",
        views.institution_evaluated_siae_detail,
        name="institution_evaluated_siae_detail",
    ),
    path("siae_job_applications_list", views.siae_job_applications_list, name="siae_job_applications_list"),
    path(
        "siae_select_criteria/<int:evaluated_job_application_pk>/",
        views.siae_select_criteria,
        name="siae_select_criteria",
    ),
    path(
        "siae_upload_doc/<int:evaluated_administrative_criteria_pk>/",
        views.siae_upload_doc,
        name="siae_upload_doc",
    ),
    path("siae_submit_proofs", views.siae_submit_proofs, name="siae_submit_proofs"),
]
