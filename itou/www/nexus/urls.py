from django.urls import path

from itou.www.nexus import views


app_name = "nexus"

urlpatterns = [
    path("auto-login", views.auto_login, name="auto_login"),
]
