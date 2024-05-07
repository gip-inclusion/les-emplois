from django.urls import path

from itou.www.siae_evaluations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siae_evaluations_views"

urlpatterns = [
    path("samples_selection", views.samples_selection, name="samples_selection"),
    path(
        "<int:evaluation_campaign_pk>/calendar/",
        views.campaign_calendar,
        name="campaign_calendar",
    ),
    path(
        "institution_evaluated_siae_list/<int:evaluation_campaign_pk>/",
        views.institution_evaluated_siae_list,
        name="institution_evaluated_siae_list",
    ),
    path(
        "evaluated_siae_detail/<int:evaluated_siae_pk>/",
        views.evaluated_siae_detail,
        name="evaluated_siae_detail",
    ),
    path(
        "institution_evaluated_siae_notify/<int:evaluated_siae_pk>/",
        views.InstitutionEvaluatedSiaeNotifyStep1View.as_view(),
        name="institution_evaluated_siae_notify_step1",
    ),
    path(
        "institution_evaluated_siae_sanctions/<int:evaluated_siae_pk>/",
        views.InstitutionEvaluatedSiaeNotifyStep2View.as_view(),
        name="institution_evaluated_siae_notify_step2",
    ),
    path(
        "institution_evaluated_siae_sanctions_details/<int:evaluated_siae_pk>/",
        views.InstitutionEvaluatedSiaeNotifyStep3View.as_view(),
        name="institution_evaluated_siae_notify_step3",
    ),
    path("institution_evaluated_siae_sanction_instruction/", views.sanctions_helper_view, name="sanctions_helper"),
    path(
        "institution_evaluated_siae_sanction/<int:evaluated_siae_pk>/",
        views.evaluated_siae_sanction,
        {"viewer_type": "institution"},
        name="institution_evaluated_siae_sanction",
    ),
    path(
        "evaluated_siae_sanction/<int:evaluated_siae_pk>/",
        views.evaluated_siae_sanction,
        {"viewer_type": "siae"},
        name="siae_sanction",
    ),
    path(
        "evaluated_job_application/<int:evaluated_job_application_pk>/",
        views.evaluated_job_application,
        name="evaluated_job_application",
    ),
    path(
        "institution_evaluated_administrative_criteria/<int:evaluated_administrative_criteria_pk>/<slug:action>",
        views.institution_evaluated_administrative_criteria,
        name="institution_evaluated_administrative_criteria",
    ),
    path(
        "institution_evaluated_siae_validation/<int:evaluated_siae_pk>/",
        views.institution_evaluated_siae_validation,
        name="institution_evaluated_siae_validation",
    ),
    path(
        "siae_job_applications_list/<int:evaluated_siae_pk>/",
        views.siae_job_applications_list,
        name="siae_job_applications_list",
    ),
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
    path("siae_submit_proofs/<int:evaluated_siae_pk>/", views.siae_submit_proofs, name="siae_submit_proofs"),
    path("view_proof/<int:evaluated_administrative_criteria_id>/", views.view_proof, name="view_proof"),
]
