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
    path("export-cta", views.export_cta, name="export_cta"),
    path("merge-users", views.merge_users, name="merge_users"),
    path(
        "merge-users/<uuid:user_1_public_id>/<uuid:user_2_public_id>",
        views.merge_users_confirm,
        name="merge_users_confirm",
    ),
    path("otp/setup", views.otp_setup, name="otp_setup"),
    path("otp/confirm", views.otp_confirm, name="otp_confirm"),
]
