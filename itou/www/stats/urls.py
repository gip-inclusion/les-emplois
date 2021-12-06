from django.urls import path

from itou.www.stats import views


app_name = "stats"

urlpatterns = [
    path("", views.public_basic_stats, name="public_basic_stats"),
    path("cd/", views.stats_cd, name="stats_cd"),
    path("siae/", views.stats_siae, name="stats_siae"),
    path("ddets/", views.stats_ddets, name="stats_ddets"),
    path("dreets/", views.stats_dreets, name="stats_dreets"),
    path("dgefp/", views.stats_dgefp, name="stats_dgefp"),
    path("pilotage/<int:dashboard_id>/", views.public_pilotage_stats, name="public_pilotage_stats"),
]
