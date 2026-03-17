from django.urls import path

from itou.www.otp_views import views


app_name = "otp_views"

urlpatterns = [
    path("devices", views.otp_devices, name="otp_devices"),
    path("confirm/<int:device_id>", views.otp_confirm_device, name="otp_confirm_device"),
]
