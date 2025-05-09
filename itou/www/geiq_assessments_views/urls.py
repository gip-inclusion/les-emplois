from django.urls import path

from itou.www.geiq_assessments_views import views


app_name = "geiq_assessments_views"

urlpatterns = [
    # GEIQ urls
    path("", views.list_for_geiq, name="list_for_geiq"),
    path("create", views.create_assessment, name="create"),
    path("<uuid:pk>", views.assessment_details_for_geiq, name="details_for_geiq"),
    path("<uuid:pk>/kpi", views.assessment_kpi, name="assessment_kpi"),
    path("<uuid:pk>/result", views.assessment_result, name="assessment_result"),
    # path("details/<uuid:pk>/result", views.assessment_result, name="assessment_result"),
    path(
        "<uuid:pk>/summary-document",
        views.assessment_get_file,
        name="summary_document",
        kwargs={"file_field": "summary_document_file"},
    ),
    path(
        "<uuid:pk>/summary-document/sync",
        views.assessment_sync_file,
        name="sync_summary_document",
        kwargs={"file_field": "summary_document_file"},
    ),
    path(
        "<uuid:pk>/structure-financial-asssessment",
        views.assessment_get_file,
        name="structure_financial_assessment",
        kwargs={"file_field": "structure_financial_assessment_file"},
    ),
    path(
        "<uuid:pk>/structure-financial-asssessment/sync",
        views.assessment_sync_file,
        name="sync_structure_financial_assessment",
        kwargs={"file_field": "structure_financial_assessment_file"},
    ),
    path(
        "<uuid:pk>/action-financial-asssessment",
        views.assessment_get_file,
        name="action_financial_assessment",
        kwargs={"file_field": "action_financial_assessment_file"},
    ),
    path(
        "<uuid:pk>/action-financial-asssessment/upload",
        views.upload_action_financial_assessment,
        name="upload_action_financial_assessment",
    ),
    path(
        "<uuid:pk>/comment",
        views.assessment_comment,
        name="assessment_comment",
    ),
    path(
        "<uuid:pk>/contracts/sync",
        views.assessment_contracts_sync,
        name="assessment_contracts_sync",
    ),
    path(
        "<uuid:pk>/contracts",
        views.assessment_contracts_list,
        name="assessment_contracts_list",
    ),
    path(
        "contracts/<uuid:contract_pk>/include",
        views.assessment_contracts_toggle,
        name="assessment_contracts_include",
        kwargs={"new_value": True},
    ),
    path(
        "contracts/<uuid:contract_pk>/exclude",
        views.assessment_contracts_toggle,
        name="assessment_contracts_exclude",
        kwargs={"new_value": False},
    ),
    path(
        "contracts/<uuid:contract_pk>/<str:tab>",
        views.assessment_contracts_details,
        name="assessment_contracts_detail",
    ),
    # institution urls
    path("institution/", views.list_for_institution, name="list_for_institution"),
    path("institution/<uuid:pk>", views.assessment_details_for_institution, name="details_for_institution"),
    path("institution/<uuid:pk>/review", views.assessment_review, name="assessment_review"),
]
