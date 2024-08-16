from django.urls import path

from itou.www.stats import views


app_name = "stats"


urlpatterns = [
    # Public stats.
    path("", views.stats_public, name="stats_public"),
    path("pilotage/<int:dashboard_id>", views.stats_pilotage, name="stats_pilotage"),
    path("redirect/<str:dashboard_name>", views.stats_redirect, name="redirect"),
    # Employer stats.
    path("siae/aci", views.stats_siae_aci, name="stats_siae_aci"),
    path("siae/etp", views.stats_siae_etp, name="stats_siae_etp"),
    path("siae/orga_etp", views.stats_siae_orga_etp, name="stats_siae_orga_etp"),
    path("siae/hiring", views.stats_siae_hiring, name="stats_siae_hiring"),
    path("siae/auto_prescription", views.stats_siae_auto_prescription, name="stats_siae_auto_prescription"),
    path(
        "siae/follow_siae_evaluation",
        views.stats_siae_follow_siae_evaluation,
        name="stats_siae_follow_siae_evaluation",
    ),
    path("siae/hiring_report", views.stats_siae_hiring_report, name="stats_siae_hiring_report"),
    # Prescriber stats - CD.
    path("cd/iae", views.stats_cd_iae, name="stats_cd_iae"),
    path("cd/hiring", views.stats_cd_hiring, name="stats_cd_hiring"),
    path("cd/brsa", views.stats_cd_brsa, name="stats_cd_brsa"),
    path("cd/aci", views.stats_cd_aci, name="stats_cd_aci"),
    # Prescriber stats - FT.
    # Legacy `pe` term is used in URLs for retroactivity in Matomo stats but in fact it means `ft`.
    path("pe/delay/main", views.stats_ft_delay_main, name="stats_ft_delay_main"),
    path("pe/delay/raw", views.stats_ft_delay_raw, name="stats_ft_delay_raw"),
    path("pe/conversion/main", views.stats_ft_conversion_main, name="stats_ft_conversion_main"),
    path("pe/conversion/raw", views.stats_ft_conversion_raw, name="stats_ft_conversion_raw"),
    path("pe/state/main", views.stats_ft_state_main, name="stats_ft_state_main"),
    path("pe/state/raw", views.stats_ft_state_raw, name="stats_ft_state_raw"),
    path("pe/tension", views.stats_ft_tension, name="stats_ft_tension"),
    # Authorized prescribers' stats
    path("ph/state/main", views.stats_ph_state_main, name="stats_ph_state_main"),
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
    path(
        "ddets/follow_siae_evaluation",
        views.stats_ddets_iae_follow_siae_evaluation,
        name="stats_ddets_iae_follow_siae_evaluation",
    ),
    path(
        "ddets/follow_prolongation",
        views.stats_ddets_iae_follow_prolongation,
        name="stats_ddets_iae_follow_prolongation",
    ),
    path(
        "ddets/tension",
        views.stats_ddets_iae_tension,
        name="stats_ddets_iae_tension",
    ),
    path("ddets/iae", views.stats_ddets_iae_iae, name="stats_ddets_iae_iae"),
    path("ddets/siae_evaluation", views.stats_ddets_iae_siae_evaluation, name="stats_ddets_iae_siae_evaluation"),
    path("ddets/hiring", views.stats_ddets_iae_hiring, name="stats_ddets_iae_hiring"),
    path("ddets/state", views.stats_ddets_iae_state, name="stats_ddets_iae_state"),
    path("ddets/aci", views.stats_ddets_iae_aci, name="stats_ddets_iae_aci"),
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
    path(
        "dreets/follow_siae_evaluation",
        views.stats_dreets_iae_follow_siae_evaluation,
        name="stats_dreets_iae_follow_siae_evaluation",
    ),
    path(
        "dreets/follow_prolongation",
        views.stats_dreets_iae_follow_prolongation,
        name="stats_dreets_iae_follow_prolongation",
    ),
    path(
        "dreets/tension",
        views.stats_dreets_iae_tension,
        name="stats_dreets_iae_tension",
    ),
    path("dreets/iae", views.stats_dreets_iae_iae, name="stats_dreets_iae_iae"),
    path("dreets/hiring", views.stats_dreets_iae_hiring, name="stats_dreets_iae_hiring"),
    path("dreets/state", views.stats_dreets_iae_hiring, name="stats_dreets_iae_state"),
    # Institution stats - DGEFP - nation level.
    path("dgefp/auto_prescription", views.stats_dgefp_iae_auto_prescription, name="stats_dgefp_iae_auto_prescription"),
    path(
        "dgefp/follow_siae_evaluation",
        views.stats_dgefp_iae_follow_siae_evaluation,
        name="stats_dgefp_iae_follow_siae_evaluation",
    ),
    path(
        "dgefp/follow_prolongation",
        views.stats_dgefp_iae_follow_prolongation,
        name="stats_dgefp_iae_follow_prolongation",
    ),
    path(
        "dgefp/tension",
        views.stats_dgefp_iae_tension,
        name="stats_dgefp_iae_tension",
    ),
    path("dgefp/iae", views.stats_dgefp_iae_iae, name="stats_dgefp_iae_iae"),
    path(
        "dgefp/ph_prescription",
        views.stats_dgefp_iae_ph_prescription,
        name="stats_dgefp_iae_ph_prescription",
    ),
    path("dgefp/hiring", views.stats_dgefp_iae_hiring, name="stats_dgefp_iae_hiring"),
    path("dgefp/state", views.stats_dgefp_iae_state, name="stats_dgefp_iae_state"),
    path("dgefp/siae_evaluation", views.stats_dgefp_iae_siae_evaluation, name="stats_dgefp_iae_siae_evaluation"),
    path("dgefp/af", views.stats_dgefp_iae_af, name="stats_dgefp_iae_af"),
    # Institution stats - DIHAL - nation level.
    path("dihal/state", views.stats_dihal_state, name="stats_dihal_state"),
    # Institution stats - DRIHL - region level - IDF only.
    path("drihl/state", views.stats_drihl_state, name="stats_drihl_state"),
    # Institution stats - IAE Network - nation level.
    path("iae_network/hiring", views.stats_iae_network_hiring, name="stats_iae_network_hiring"),
]
