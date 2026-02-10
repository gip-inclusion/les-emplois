from django.urls import path, reverse_lazy
from django.views.generic import RedirectView
from itoutils.django.nexus.views import auto_login

from itou.www.nexus import views


app_name = "nexus"

urlpatterns = [
    path("", RedirectView.as_view(url=reverse_lazy("nexus:homepage")), name="index"),
    path("auto-login", auto_login, name="auto_login"),
    path("login", views.login, name="login"),
    path("homepage", views.HomePageView.as_view(), name="homepage"),
    path("structures", views.StructuresView.as_view(), name="structures"),
    path("service/dora", views.DoraView.as_view(), name="dora"),
    path("service/emplois", views.EmploisView.as_view(), name="emplois"),
    path("service/marche", views.MarcheView.as_view(), name="marche"),
    path("service/mon-recap", views.MonRecapView.as_view(), name="mon_recap"),
    path("service/mon-recap/activate", views.activate_mon_recap, name="activate_mon_recap"),
    path("service/pilotage", views.PilotageView.as_view(), name="pilotage"),
    path("contact", views.ContactView.as_view(), name="contact"),
]
