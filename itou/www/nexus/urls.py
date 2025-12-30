from django.urls import path
from itoutils.django.nexus.views import auto_login

from itou.www.nexus import views


app_name = "nexus"

urlpatterns = [
    path("auto-login", auto_login, name="auto_login"),
    path("accueil", views.HomePageView.as_view(), name="homepage"),
    path("activate/<str:service>", views.activate, name="activate"),
    path("service/communaute", views.CommunauteView.as_view(), name="communaute"),
    path("service/marche", views.MarcheView.as_view(), name="marche"),
    path("service/mon-recap", views.MonRecapView.as_view(), name="mon_recap"),
    path("service/pilotage", views.PilotageView.as_view(), name="pilotage"),
]
