from django.urls import path
from django.views.generic import TemplateView

from itou.www.otp_views import views


app_name = "otp_views"

urlpatterns = [
    path("devices", views.otp_devices, name="otp_devices"),
    path(
        "enrollment-step-0",
        views.enrollment_step_0_intro,
        name="enrollment_step_0_intro",
    ),
    path(
        "enrollment-step-1",
        views.enrollment_step_1_choose_device_type,
        name="enrollment_step_1_choose_device_type",
    ),
    path(
        "enrollment-step-2-and-3",
        views.enrollment_step_2_and_3_confirm_device,
        name="enrollment_step_2_and_3_confirm_device",
    ),
    path(
        "login-with-backup-code",
        views.login_with_backup_code,
        name="login_with_backup_code",
    ),
    path("verify", views.VerifyOTPView.as_view(), name="verify_otp"),
    path("reset-request/step-1", views.reset_request_init, name="reset_request_init"),
    path("reset-request/created", views.reset_request_created, name="reset_request_created"),
    path("reset-request/cancel", views.reset_request_cancel, name="reset_request_self_cancel"),
    path(
        "reset-request/cancelled",
        TemplateView.as_view(template_name="otp_views/reset_request_self_cancelled.html"),
        name="reset_request_self_cancelled",
    ),
    path("reset-request/reset/<str:nonce>", views.reset_request_do_reset, name="reset_request_do_reset"),
]
