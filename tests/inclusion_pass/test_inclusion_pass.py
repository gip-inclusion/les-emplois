from urllib.parse import urlencode

import pytest
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.companies.enums import ProSupportReportBarrier, ProSupportReportSolution
from itou.inclusion_pass import catalogue, services
from itou.inclusion_pass.models import AccesDonnee, NotificationPrescripteur
from itou.insertion.enums import OrientationStatus
from itou.job_applications.enums import SenderKind
from itou.www.inclusion_pass_views.views import DEMO_PERSONA_EMAIL
from tests.companies.factories import CompanyMembershipFactory
from tests.inclusion_pass.factories import (
    AccompagnementFactory,
    BilanInterventionFactory,
    OffreurFactory,
    OffreurMembershipFactory,
)
from tests.insertion.factories import OrientationFactory, ServiceFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, ProfessionalFactory


def _statuts(offreur, personne):
    return {
        ligne["cle"]: ligne["statut"]
        for bloc in services.donnees_pour_offreur(offreur, personne)
        for ligne in bloc["lignes"]
    }


def test_seul_le_consenti_est_visible():
    personne = JobSeekerFactory()
    offreur = OffreurFactory(donnees_demandees=[catalogue.IDENTITE, catalogue.STATUT_RSA, catalogue.AAH])
    services.accorder(personne, offreur, [catalogue.IDENTITE, catalogue.STATUT_RSA])

    assert _statuts(offreur, personne) == {
        catalogue.IDENTITE: "partagee",
        catalogue.STATUT_RSA: "partagee",
        catalogue.AAH: "non_partagee",
    }
    actions = set(AccesDonnee.objects.filter(personne=personne).values_list("action", flat=True))
    assert actions == {AccesDonnee.Action.OCTROI, AccesDonnee.Action.RECUPERATION, AccesDonnee.Action.CONSULTATION}


def test_donnee_non_demandee_ignoree():
    personne = JobSeekerFactory()
    offreur = OffreurFactory(donnees_demandees=[catalogue.IDENTITE])
    services.accorder(personne, offreur, [catalogue.AAH])

    assert services.cles_consenties(personne, offreur) == set()


def test_retrait():
    personne = JobSeekerFactory()
    offreur = OffreurFactory()
    services.accorder(personne, offreur, [catalogue.IDENTITE, catalogue.STATUT_RSA])
    services.retirer(personne, offreur, catalogue.STATUT_RSA)

    lignes = {
        ligne["cle"]: ligne for bloc in services.donnees_pour_offreur(offreur, personne) for ligne in bloc["lignes"]
    }
    assert lignes[catalogue.STATUT_RSA]["statut"] == "retiree"
    assert lignes[catalogue.STATUT_RSA]["texte"] is None
    assert lignes[catalogue.IDENTITE]["statut"] == "partagee"
    assert AccesDonnee.objects.filter(personne=personne, action=AccesDonnee.Action.RETRAIT).count() == 1

    services.retirer(personne, offreur)
    assert services.cles_consenties(personne, offreur) == set()


def test_prescripteur_prevenu_lors_d_un_second_passage():
    offreur = OffreurFactory()
    orientation = OrientationFactory(service=ServiceFactory(structure=offreur.structure))
    personne = orientation.beneficiary
    services.accorder(personne, offreur, [])
    assert not NotificationPrescripteur.objects.exists()

    services.accorder(personne, offreur, [catalogue.INFORMER_PRESCRIPTEUR])
    services.accorder(personne, offreur, [catalogue.INFORMER_PRESCRIPTEUR])
    notification = NotificationPrescripteur.objects.get()
    assert notification.prescripteur == orientation.sender_prescriber_organization
    assert notification.lue_le is None


def test_activation_du_pass_valide_l_orientation_sans_prevenir_le_prescripteur():
    offreur = OffreurFactory()
    orientation = OrientationFactory(service=ServiceFactory(structure=offreur.structure))
    services.accorder(orientation.beneficiary, offreur, [catalogue.IDENTITE])

    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.ACCEPTED
    assert not NotificationPrescripteur.objects.exists()


def test_orientation_envoyee_par_un_employeur_ne_notifie_aucun_prescripteur():
    # The prescriber of a job application cannot see an orientation sent by a company: no notification for it
    offreur = OffreurFactory()
    employeur = CompanyMembershipFactory()
    orientation = OrientationFactory(
        service=ServiceFactory(structure=offreur.structure),
        sender=employeur.user,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=employeur.company,
        sender_prescriber_organization=None,
    )
    JobApplicationFactory(job_seeker=orientation.beneficiary, sent_by_prescriber=True)
    services.accorder(orientation.beneficiary, offreur, [catalogue.INFORMER_PRESCRIPTEUR])

    assert not NotificationPrescripteur.objects.exists()


def test_nouveau_passage_apres_un_accompagnement_termine():
    offreur = OffreurFactory()
    orientation = OrientationFactory(service=ServiceFactory(structure=offreur.structure))
    personne = orientation.beneficiary
    premier = services.accorder(personne, offreur, [catalogue.INFORMER_PRESCRIPTEUR])
    services.envoyer_bilan(BilanInterventionFactory.build(accompagnement=premier, auteur=ProfessionalFactory()))

    # The old orientation led to the ended follow-up: the new one starts without it
    second = services.accorder(personne, offreur, [])
    assert second != premier
    assert second.orientation is None
    assert NotificationPrescripteur.objects.count() == 1


def test_sans_orientation_le_prescripteur_n_est_pas_prevenu():
    offreur = OffreurFactory()
    accompagnement = services.accorder(JobSeekerFactory(), offreur, [catalogue.INFORMER_PRESCRIPTEUR])

    assert accompagnement.prescripteur is None
    assert not NotificationPrescripteur.objects.exists()


def test_qr_code_sans_orientation_demarche_en_autonomie(client):
    # The demo prescriber account must not be used as a default prescriber anymore
    PrescriberMembershipFactory(user__email=services.DEMO_PRESCRIPTEUR_EMAIL)
    offreur = OffreurFactory()
    personne = JobSeekerFactory()
    client.force_login(personne)
    client.post(reverse("inclusion_pass:consentement", args=[offreur.uuid_accueil]), {"donnees": [catalogue.IDENTITE]})

    assert personne.pass_accompagnements.get().prescripteur is None


@override_settings(SHOW_DEMO_ACCOUNTS_BANNER=False)
def test_connexion_demo_indisponible_en_production(client):
    JobSeekerFactory(email=DEMO_PERSONA_EMAIL)
    offreur = OffreurFactory()

    response = client.get(reverse("inclusion_pass:accueil", args=[offreur.uuid_accueil]))
    assertNotContains(response, "Connexion simulée")
    response = client.post(reverse("inclusion_pass:connexion_demo"))
    assert response.status_code == 404


@override_settings(SHOW_DEMO_ACCOUNTS_BANNER=True)
def test_parcours_complet(client):
    personne = JobSeekerFactory(email=DEMO_PERSONA_EMAIL)
    membre = OffreurMembershipFactory()
    offreur = membre.offreur
    orientation = OrientationFactory(beneficiary=personne, service=ServiceFactory(structure=offreur.structure))
    prescripteur = orientation.sender_prescriber_organization

    # The person scans the reception QR code, logs in and shares part of the requested data
    response = client.get(reverse("inclusion_pass:accueil", args=[offreur.uuid_accueil]))
    assertContains(response, f"<strong>{offreur.display_name}</strong>")
    response = client.post(reverse("inclusion_pass:connexion_demo"))
    assert response.url == reverse("inclusion_pass:consentement", args=[offreur.uuid_accueil])
    response = client.get(response.url)
    assertContains(response, '<legend class="h3">')
    response = client.post(
        response.wsgi_request.path,
        {"donnees": [catalogue.IDENTITE, catalogue.STATUT_RSA, catalogue.INFORMER_PRESCRIPTEUR, catalogue.SUIVI_LONG]},
    )
    assertContains(client.get(response.url), "Votre pass est activé.")
    accompagnement = personne.pass_accompagnements.get()
    assert accompagnement.orientation == orientation
    assert accompagnement.prescripteur == prescripteur
    # Activating the pass validates the orientation, without any action from the offreur
    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.ACCEPTED

    # The offreur sees the new person and the record, without the mockup "Provenance des données" block
    client.force_login(membre.user)
    response = client.get(reverse("dashboard:index"))
    assertContains(response, f"<span>{personne.get_inverted_full_name()}</span>")
    fiche_url = reverse("inclusion_pass:fiche", args=[accompagnement.pk])
    response = client.get(fiche_url)
    assertContains(response, f"<h1>{personne.get_inverted_full_name()}</h1>")
    assertContains(response, "<strong>Non partagé</strong>")
    assertContains(response, "Orientation reçue</span>")
    assertNotContains(response, "Provenance des données")

    bilan_url = reverse("inclusion_pass:bilan_intervention", args=[accompagnement.pk])
    client.post(bilan_url)
    assert accompagnement.situations.count() == 3
    response = client.get(reverse("dashboard:index_stats"))
    assertContains(response, '<canvas data-pass-graphique="graphique-qpv-donnees"')
    csv = client.get(reverse("inclusion_pass:pilotage_csv"))
    assert "Sorties positives à 12 mois" in csv.text

    # The prescriber who sent the orientation is notified in the existing screens, until the orientation is opened
    client.force_login(PrescriberMembershipFactory(organization=prescripteur).user)
    badge = '<span class="badge rounded-pill badge-xs bg-warning">1</span>'
    assertContains(client.get(reverse("dashboard:index")), badge)
    liste_url = reverse("insertion_views:orientations_list")
    assertContains(client.get(liste_url), "Pass inclusion activé le")
    details_url = reverse("insertion_views:orientation_details_for_sender", args=[orientation.id])
    assert client.head(details_url).status_code == 200
    assertContains(client.get(liste_url), "Pass inclusion activé le")
    client.get(details_url)
    assertNotContains(client.get(liste_url), "Pass inclusion activé le")
    assertNotContains(client.get(reverse("dashboard:index")), badge)


def test_qr_code_partage_par_plusieurs_personnes(client):
    offreur = OffreurFactory()
    url = reverse("inclusion_pass:consentement", args=[offreur.uuid_accueil])
    for personne in JobSeekerFactory.create_batch(2):
        client.force_login(personne)
        client.post(url, {"donnees": [catalogue.IDENTITE]})

    assert offreur.accompagnements.count() == 2


def test_demandes_recues(client):
    membre = OffreurMembershipFactory()
    service = ServiceFactory(structure=membre.offreur.structure)
    recue = OrientationFactory(service=service)
    autre = OrientationFactory()
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:demandes_recues"))
    assertContains(response, f">{recue.beneficiary.get_inverted_full_name()}</a>")
    assertNotContains(response, autre.beneficiary.get_inverted_full_name())
    response = client.get(reverse("inclusion_pass:orientation_recue", args=[autre.id]))
    assert response.status_code == 404

    detail_url = reverse("inclusion_pass:orientation_recue", args=[recue.id])
    assertContains(client.get(detail_url), '<button class="btn btn-lg btn-white btn-block btn-ico')
    client.post(detail_url, {"action": "accept"})
    recue.refresh_from_db()
    assert recue.status == OrientationStatus.ACCEPTED


def test_refuser_une_demande_recue(client):
    membre = OffreurMembershipFactory()
    orientation = OrientationFactory(service=ServiceFactory(structure=membre.offreur.structure))
    client.force_login(membre.user)

    response = client.post(
        reverse("inclusion_pass:refuser_orientation", args=[orientation.id]),
        {"refusal_reasons": ["not_reachable"], "refusal_details": "Injoignable"},
    )
    assert response.url == reverse("inclusion_pass:orientation_recue", args=[orientation.id])
    orientation.refresh_from_db()
    assert orientation.status == OrientationStatus.REFUSED


def test_usagers_limites_a_l_offreur(client):
    membre = OffreurMembershipFactory()
    accompagnee = JobSeekerFactory()
    services.accorder(accompagnee, membre.offreur, [catalogue.IDENTITE])
    ailleurs = JobSeekerFactory()
    services.accorder(ailleurs, OffreurFactory(), [catalogue.IDENTITE])
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:usagers"))
    assertContains(response, f">{accompagnee.get_inverted_full_name()}</a>")
    assertNotContains(response, ailleurs.get_inverted_full_name())
    autre_fiche = ailleurs.pass_accompagnements.get()
    assert client.get(reverse("inclusion_pass:fiche", args=[autre_fiche.pk])).status_code == 404


def test_usager_en_demarche_autonome(client):
    membre = OffreurMembershipFactory()
    services.accorder(JobSeekerFactory(), membre.offreur, [catalogue.IDENTITE])
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:usagers"))
    assertContains(response, "<td>Démarche en autonomie</td>")
    assertNotContains(response, '<th scope="col">Arrivée</th>')


def test_onglet_accompagnateurs(client):
    membre = OffreurMembershipFactory()
    accompagnement = AccompagnementFactory(offreur=membre.offreur)
    prescripteur = PrescriberMembershipFactory()
    assignment = JobSeekerAssignmentFactory(
        job_seeker=accompagnement.personne,
        professional=prescripteur.user,
        prescriber_organization=prescripteur.organization,
    )
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:accompagnateurs", args=[accompagnement.pk]))
    assertContains(response, "Accompagnateurs actuels (1)")
    assertContains(response, f"<h3>{assignment.professional.get_full_name()}</h3>")
    assertContains(response, assignment.prescriber_organization.display_name)


def test_bilan_de_l_intervention(client):
    membre = OffreurMembershipFactory()
    accompagnement = AccompagnementFactory(offreur=membre.offreur)
    client.force_login(membre.user)
    bilan_url = reverse("inclusion_pass:bilan_intervention", args=[accompagnement.pk])
    remplir_url = reverse("inclusion_pass:remplir_bilan", args=[accompagnement.pk])

    assertContains(client.get(bilan_url), f'href="{remplir_url}')
    response = client.get(remplir_url)
    assertContains(response, "L’usager a-t-il des freins périphériques identifiés")
    assertNotContains(response, ProSupportReportSolution.RENEWAL.label)
    response = client.post(
        remplir_url,
        {
            "barriers": [ProSupportReportBarrier.MOBILITY],
            "autonomy": 3,
            "has_solution": "True",
            "solution": ProSupportReportSolution.TRAINING,
        },
    )
    assertRedirects(response, f"{bilan_url}?{urlencode({'back_url': reverse('inclusion_pass:usagers')})}")

    # Sending the report ends the follow-up, and the report can no longer be changed
    accompagnement.refresh_from_db()
    assert accompagnement.ended_at is not None
    assert accompagnement.bilan.auteur == membre.user
    response = client.get(bilan_url)
    assertContains(response, ProSupportReportBarrier.MOBILITY.label)
    assertContains(response, "Solution après l’accompagnement")
    assertContains(response, ProSupportReportSolution.TRAINING.label)
    assert client.get(remplir_url).status_code == 404


def test_bilan_de_l_intervention_deja_rempli():
    bilan = BilanInterventionFactory(barriers=[ProSupportReportBarrier.DIGITAL])

    assert bilan.get_barriers_display() == [ProSupportReportBarrier.DIGITAL.label]


def test_pages_structure(client):
    membre = OffreurMembershipFactory(offreur__structure__description="Une auto-école pour tous")
    service = ServiceFactory(structure=membre.offreur.structure)
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:presentation"))
    assertContains(response, '<h2 class="mb-1">Présentation de la structure</h2>')
    assertContains(response, "<p>Une auto-école pour tous</p>")
    response = client.get(reverse("inclusion_pass:offres"))
    assertContains(response, f'class="btn-link">{service.name}</a>')
    response = client.get(reverse("inclusion_pass:qr_code_accueil"))
    assertContains(response, reverse("inclusion_pass:accueil", args=[membre.offreur.uuid_accueil]))


@pytest.mark.parametrize(
    "modele,ligne",
    [
        ("fse", "Femmes;1"),
        ("cd", "Bénéficiaires du RSA accompagnés;1"),
        ("complet", "Personnes accompagnées;2"),
    ],
)
def test_exports_du_pilotage(client, modele, ligne):
    membre = OffreurMembershipFactory()
    AccompagnementFactory(offreur=membre.offreur, personne__title="MME", statuts_entree={catalogue.STATUT_RSA: True})
    AccompagnementFactory(offreur=membre.offreur, personne__title="M", statuts_entree={catalogue.STATUT_RSA: False})
    client.force_login(membre.user)

    response = client.get(reverse("inclusion_pass:pilotage_csv"), {"modele": modele})
    assert response["Content-Disposition"] == f'attachment; filename="bilan-impact-{modele}.csv"'
    lignes = response.content.decode().splitlines()
    assert lignes[0] == f"Structure;{membre.offreur.display_name}"
    assert ligne in lignes


def test_export_du_pilotage_inconnu(client):
    client.force_login(OffreurMembershipFactory().user)

    assert client.get(reverse("inclusion_pass:pilotage_csv"), {"modele": "autre"}).status_code == 404


@pytest.mark.parametrize(
    "url_name", ["inclusion_pass:demandes_recues", "inclusion_pass:usagers", "inclusion_pass:presentation"]
)
def test_pages_offreur_refusees_aux_autres_professionnels(client, url_name):
    client.force_login(CompanyMembershipFactory().user)

    assert client.get(reverse(url_name)).status_code == 403


@pytest.mark.parametrize("url_name", ["inclusion_pass:accompagnateurs", "inclusion_pass:remplir_bilan"])
def test_pages_usager_refusees_aux_autres_professionnels(client, url_name):
    client.force_login(CompanyMembershipFactory().user)

    assert client.get(reverse(url_name, args=[AccompagnementFactory().pk])).status_code == 403
