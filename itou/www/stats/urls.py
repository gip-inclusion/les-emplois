from django.urls import path

from itou.www.stats import views


app_name = "stats"

urlpatterns = [
    # Public stats.
    path("", views.stats_public, name="stats_public"),
    path("pilotage/<int:dashboard_id>/", views.stats_pilotage, name="stats_pilotage"),
    # Employer stats.
    path("siae/etp/", views.stats_siae_etp, name="stats_siae_etp"),
    path("siae/hiring/", views.stats_siae_hiring, name="stats_siae_hiring"),
    # Prescriber stats.
    path("cd/", views.stats_cd, name="stats_cd"),
    path("pe/", views.stats_pe, name="stats_pe"),
    # Institution stats - DDETS - department level.
    path("ddets/iae/", views.stats_ddets_iae, name="stats_ddets_iae"),
    path("ddets/diagnosis_control/", views.stats_ddets_diagnosis_control, name="stats_ddets_diagnosis_control"),
    path("ddets/hiring/", views.stats_ddets_hiring, name="stats_ddets_hiring"),
    # Institution stats - DREETS - region level.
    path("dreets/iae/", views.stats_dreets_iae, name="stats_dreets_iae"),
    path("dreets/hiring/", views.stats_dreets_hiring, name="stats_dreets_hiring"),
    # Institution stats - DGEFP - nation level.
    path("dgefp/iae/", views.stats_dgefp_iae, name="stats_dgefp_iae"),
    path("dgefp/diagnosis_control/", views.stats_dgefp_diagnosis_control, name="stats_dgefp_diagnosis_control"),
    path("dgefp/af/", views.stats_dgefp_af, name="stats_dgefp_af"),
]
