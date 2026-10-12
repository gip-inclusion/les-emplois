from django.urls import path

from itou.www.selftest import views


app_name = "selftest"

urlpatterns = [
    path("headers", views.headers, name="headers"),
]
