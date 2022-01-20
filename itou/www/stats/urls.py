from django.urls import path

from itou.www.stats import views


app_name = "stats"

urlpatterns = [
    path("", views.stats_public, name="stats_public"),
    path("cd/", views.stats_cd, name="stats_cd"),
    path("ddets/diagnosis_control/", views.stats_ddets_diagnosis_control, name="stats_ddets_diagnosis_control"),
    path("ddets/overview/", views.stats_ddets_overview, name="stats_ddets_overview"),
    path("dgefp/", views.stats_dgefp, name="stats_dgefp"),
    path("dreets/", views.stats_dreets, name="stats_dreets"),
    path("pilotage/<int:dashboard_id>/", views.stats_pilotage, name="stats_pilotage"),
    path("siae/", views.stats_siae, name="stats_siae"),
]
