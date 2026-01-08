from django.urls import path
from itoutils.django.nexus.views import auto_login

from itou.www.nexus import views


app_name = "nexus"

urlpatterns = [
    path("auto-login", auto_login, name="auto_login"),
    path("homepage", views.HomePageView.as_view(), name="homepage"),
]
