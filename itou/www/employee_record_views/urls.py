from django.urls import path

from itou.www.employee_record_views import views


app_name = "employee_record_views"

urlpatterns = [
    path(
        "add/",
        views.AddView.as_view(url_name="employee_record_views:add"),
        name="add",
    ),
    path(
        "add/<slug:step>",
        views.AddView.as_view(url_name="employee_record_views:add"),
        name="add",
    ),
    path("list", views.list_employee_records, name="list"),
    path("create/<uuid:job_application_id>", views.create, name="create"),
    path("create_step_2/<uuid:job_application_id>", views.create_step_2, name="create_step_2"),
    path("create_step_3/<uuid:job_application_id>", views.create_step_3, name="create_step_3"),
    path("create_step_4/<uuid:job_application_id>", views.create_step_4, name="create_step_4"),
    path("create_step_5/<uuid:job_application_id>", views.create_step_5, name="create_step_5"),
    path("summary/<employee_record_id>", views.summary, name="summary"),
    path("disable/<employee_record_id>", views.disable, name="disable"),
    path("reactivate/<employee_record_id>", views.reactivate, name="reactivate"),
]
