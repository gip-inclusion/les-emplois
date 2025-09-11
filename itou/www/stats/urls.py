from django.urls import path

from itou.www.stats import views


app_name = "stats"


urlpatterns = [
    # Public stats.
    path("", views.stats_public, name="stats_public"),
    path("redirect/<str:dashboard_name>", views.stats_redirect, name="redirect"),
    # Employer stats.
    path("siae/etp", views.stats_siae_etp, name="stats_siae_etp"),
    path("siae/orga_etp", views.stats_siae_orga_etp, name="stats_siae_orga_etp"),
    path("siae/hiring", views.stats_siae_hiring, name="stats_siae_hiring"),
    path("siae/auto_prescription", views.stats_siae_auto_prescription, name="stats_siae_auto_prescription"),
    path("siae/beneficiaries", views.stats_siae_beneficiaries, name="stats_siae_beneficiaries"),
    # Prescriber stats - CD.
    path("cd/iae", views.stats_cd_iae, name="stats_cd_iae"),
    path("cd/hiring", views.stats_cd_hiring, name="stats_cd_hiring"),
    path("cd/brsa", views.stats_cd_brsa, name="stats_cd_brsa"),
    path("cd/orga_etp", views.stats_cd_orga_etp, name="stats_cd_orga_etp"),
    path("cd/beneficiaries", views.stats_cd_beneficiaries, name="stats_cd_beneficiaries"),
    # Prescriber stats - FT.
    # Legacy `pe` term is used in URLs for retroactivity in Matomo stats but in fact it means `ft`.
    path("pe/conversion/main", views.stats_ft_conversion_main, name="stats_ft_conversion_main"),
    path("pe/state/main", views.stats_ft_state_main, name="stats_ft_state_main"),
    # The `ft_state_raw` URL is not referenced in this code base, but *is used* as a direct link in TB `ft_state_main`
    path("pe/state/raw", views.stats_ft_state_raw, name="stats_ft_state_raw"),
    path("pe/beneficiaries", views.stats_ft_beneficiaries, name="stats_ft_beneficiaries"),
    path("pe/hiring", views.stats_ft_hiring, name="stats_ft_hiring"),
    # Authorized prescribers' stats
    path("ph/state/main", views.stats_ph_state_main, name="stats_ph_state_main"),
    path("ph/beneficiaries", views.stats_ph_beneficiaries, name="stats_ph_beneficiaries"),
    # Institution stats - DDETS IAE - department level.
    # Legacy `ddets` term is used in URLs for retroactivity in Matomo stats but in fact it means `ddets_iae`.
    path(
        "ddets/auto_prescription",
        views.stats_ddets_iae_auto_prescription,
        name="stats_ddets_iae_auto_prescription",
    ),
    path(
        "ddets/ph_prescription",
        views.stats_ddets_iae_ph_prescription,
        name="stats_ddets_iae_ph_prescription",
    ),
    path("ddets/siae_evaluation", views.stats_ddets_iae_siae_evaluation, name="stats_ddets_iae_siae_evaluation"),
    path("ddets/hiring", views.stats_ddets_iae_hiring, name="stats_ddets_iae_hiring"),
    path("ddets/state", views.stats_ddets_iae_state, name="stats_ddets_iae_state"),
    path("ddets/orga_etp", views.stats_ddets_iae_orga_etp, name="stats_ddets_iae_orga_etp"),
    # Institution stats - DDETS LOG - department level.
    path("ddets_log/state", views.stats_ddets_log_state, name="stats_ddets_log_state"),
    # Institution stats - DREETS IAE - region level.
    path(
        "dreets/auto_prescription",
        views.stats_dreets_iae_auto_prescription,
        name="stats_dreets_iae_auto_prescription",
    ),
    path(
        "dreets/ph_prescription",
        views.stats_dreets_iae_ph_prescription,
        name="stats_dreets_iae_ph_prescription",
    ),
    path("dreets/hiring", views.stats_dreets_iae_hiring, name="stats_dreets_iae_hiring"),
    path("dreets/state", views.stats_dreets_iae_state, name="stats_dreets_iae_state"),
    path("dreets/orga_etp", views.stats_dreets_iae_orga_etp, name="stats_dreets_iae_orga_etp"),
    # Institution stats - DGEFP - nation level.
    path("dgefp/auto_prescription", views.stats_dgefp_iae_auto_prescription, name="stats_dgefp_iae_auto_prescription"),
    path(
        "dgefp/follow_siae_evaluation",
        views.stats_dgefp_iae_follow_siae_evaluation,
        name="stats_dgefp_iae_follow_siae_evaluation",
    ),
    path(
        "dgefp/ph_prescription",
        views.stats_dgefp_iae_ph_prescription,
        name="stats_dgefp_iae_ph_prescription",
    ),
    path("dgefp/hiring", views.stats_dgefp_iae_hiring, name="stats_dgefp_iae_hiring"),
    path("dgefp/state", views.stats_dgefp_iae_state, name="stats_dgefp_iae_state"),
    path("dgefp/siae_evaluation", views.stats_dgefp_iae_siae_evaluation, name="stats_dgefp_iae_siae_evaluation"),
    path("dgefp/orga_etp", views.stats_dgefp_iae_orga_etp, name="stats_dgefp_iae_orga_etp"),
    path("dgefp/showroom/<str:dashboard_full_name>", views.stats_dgefp_iae_showroom, name="stats_dgefp_iae_showroom"),
    # Institution stats - DIHAL - nation level.
    path("dihal/state", views.stats_dihal_state, name="stats_dihal_state"),
    # Institution stats - DRIHL - region level - IDF only.
    path("drihl/state", views.stats_drihl_state, name="stats_drihl_state"),
    # Institution stats - IAE Network - nation level.
    path("iae_network/hiring", views.stats_iae_network_hiring, name="stats_iae_network_hiring"),
    # Institution stats - Convergence France - nation level.
    path("convergence/prescription", views.stats_convergence_prescription, name="stats_convergence_prescription"),
    path(
        "convergence/job_application",
        views.stats_convergence_job_application,
        name="stats_convergence_job_application",
    ),
    # Staff stats - Les Emplois
    path("staff/service_indicators", views.stats_staff_service_indicators, name="stats_staff_service_indicators"),
]
