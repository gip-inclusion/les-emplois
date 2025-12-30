from django.urls import path
from itoutils.django.nexus.views import auto_login

from itou.www.nexus import views


app_name = "nexus"

urlpatterns = [
    path("auto-login", auto_login, name="auto_login"),
    path("accueil", views.HomePageView.as_view(), name="homepage"),
    path("activate/<str:service>", views.activate, name="activate"),
    path("service/communaute", views.CommunauteView.as_view(), name="communaute"),
]
