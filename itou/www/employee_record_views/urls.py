from django.urls import path

from itou.www.employee_record_views import views


app_name = "employee_record_views"

urlpatterns = [
    path("list", views.list, name="list"),
    path("create/<uuid:job_application_id>", views.create, name="create"),
    path("create_step_2/<uuid:job_application_id>", views.create_step_2, name="create_step_2"),
    path("create_step_3/<uuid:job_application_id>", views.create_step_3, name="create_step_3"),
]
