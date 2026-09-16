from django.urls import path

from itou.www.pro_support import views


app_name = "pro_support"

urlpatterns = [
    path("webhook", views.webhook, name="webhook"),
]
