from django.urls import path

from itou.www.itou_staff_views import views


app_name = "itou_staff_views"

urlpatterns = [
    path(
        "export-job-applications-unknown-to-ft",
        views.export_job_applications_unknown_to_ft,
        name="export_job_applications_unknown_to_ft",
    ),
    path("export-ft-api-rejections", views.export_ft_api_rejections, name="export_ft_api_rejections"),
]
