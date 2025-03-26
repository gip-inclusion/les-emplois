from django.urls import path

from itou.www.geiq_assessments_views import views


app_name = "geiq_assessments_views"

urlpatterns = [
    path("list", views.list_for_geiq, name="list_for_geiq"),
    path("create", views.create_assessment, name="create"),
    path("details/<uuid:pk>", views.assessment_details, name="details"),
    path(
        "details/<uuid:pk>/summary-document",
        views.assessment_get_file,
        name="summary_document",
        kwargs={"file_field": "summary_document_file"},
    ),
    path(
        "details/<uuid:pk>/summary-document/sync",
        views.sync_summary_document,
        name="sync_summary_document",
    ),
    path(
        "details/<uuid:pk>/structure-financial-asssessment",
        views.assessment_get_file,
        name="structure_financial_assessment",
        kwargs={"file_field": "structure_financial_assessment_file"},
    ),
    path(
        "details/<uuid:pk>/structure-financial-asssessment/sync",
        views.sync_structure_financial_assessment,
        name="sync_structure_financial_assessment",
    ),
    path(
        "details/<uuid:pk>/action-financial-asssessment",
        views.assessment_get_file,
        name="action_financial_assessment",
        kwargs={"file_field": "action_financial_assessment_file"},
    ),
]
