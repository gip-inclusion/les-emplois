from django.urls import path

from itou.www.inclusion_pass_views import views


app_name = "inclusion_pass"

urlpatterns = [
    # Person side (public reception QR code, then FranceConnect)
    path("a/<uuid:uuid_accueil>/", views.accueil, name="accueil"),
    path("a/<uuid:uuid_accueil>/consentement/", views.consentement, name="consentement"),
    path("connexion-demo/", views.connexion_demo, name="connexion_demo"),
    path("mon-pass/", views.mon_pass, name="mon_pass"),
    # Offreur side (authenticated member of the offreur)
    path("structure/nouveaux-usagers/", views.nouveaux_usagers, name="nouveaux_usagers"),
    path("structure/pilotage.csv", views.pilotage_csv, name="pilotage_csv"),
    path("structure/demandes/", views.demandes_recues, name="demandes_recues"),
    path("structure/demandes/<uuid:orientation_id>/", views.orientation_recue, name="orientation_recue"),
    path(
        "structure/demandes/<uuid:orientation_id>/decliner/",
        views.refuser_orientation,
        name="refuser_orientation",
    ),
    path("structure/usagers/", views.usagers, name="usagers"),
    path("structure/usagers/<int:accompagnement_id>/", views.fiche, name="fiche"),
    path(
        "structure/usagers/<int:accompagnement_id>/accompagnateurs/",
        views.accompagnateurs,
        name="accompagnateurs",
    ),
    path("structure/usagers/<int:accompagnement_id>/bilan/", views.bilan_intervention, name="bilan_intervention"),
    path("structure/usagers/<int:accompagnement_id>/bilan/remplir/", views.remplir_bilan, name="remplir_bilan"),
    path("structure/presentation/", views.presentation, name="presentation"),
    path("structure/offres/", views.offres, name="offres"),
    path("structure/qr-code/", views.qr_code_accueil, name="qr_code_accueil"),
]
