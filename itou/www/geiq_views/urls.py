from django.urls import path

from itou.www.geiq_views import views


app_name = "geiq"

urlpatterns = [
    path(
        "assessment/<int:assessment_pk>/label-sync",
        views.label_sync,
        name="label_sync",
    ),
    path(
        "assessment/<int:assessment_pk>",
        views.assessment_info,
        name="assessment_info",
    ),
    path(
        "assessment/<int:assessment_pk>/report",
        views.assessment_report,
        name="assessment_report",
    ),
    path(
        "assessment/<int:assessment_pk>/review",
        views.assessment_review,
        name="assessment_review",
    ),
    path(
        "assessment/<int:assessment_pk>/employees/<slug:info_type>",
        views.employee_list,
        name="employee_list",
    ),
    path(
        "assessment/employee/<int:employee_pk>",
        views.employee_details,
        name="employee_details",
    ),
    path(
        "list/<int:institution_pk>",
        views.geiq_list,
        name="geiq_list",
    ),
]
