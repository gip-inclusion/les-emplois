from django.urls import path

from itou.www.otp_views import views


app_name = "otp_views"

urlpatterns = [
    path("devices", views.otp_devices, name="otp_devices"),
    path(
        "enrollment_step_0",
        views.enrollment_step_0_intro,
        name="enrollment_step_0_intro",
    ),
    path(
        "enrollment_step_1",
        views.enrollment_step_1_choose_device_type,
        name="enrollment_step_1_choose_device_type",
    ),
    path(
        "enrollment_step_2_and_3",
        views.enrollment_step_2_and_3_confirm_device,
        name="enrollment_step_2_and_3_confirm_device",
    ),
    path(
        "login_with_backup_code",
        views.login_with_backup_code,
        name="login_with_backup_code",
    ),
    path("verify", views.VerifyOTPView.as_view(), name="verify_otp"),
]
