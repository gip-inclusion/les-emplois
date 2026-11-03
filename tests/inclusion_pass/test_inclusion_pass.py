import pytest
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.inclusion_pass import catalogue, services
from itou.inclusion_pass.models import AccesDonnee, NotificationPrescripteur
from itou.insertion.enums import OrientationStatus
from itou.www.inclusion_pass_views.views import DEMO_PERSONA_EMAIL
from tests.companies.factories import CompanyMembershipFactory
from tests.inclusion_pass.factories import OffreurFactory, OffreurMembershipFactory
from tests.insertion.factories import OrientationFactory, ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory


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
    personne = JobSeekerFactory()
    offreur = OffreurFactory()
    prescripteur = PrescriberMembershipFactory().organization
    services.accorder(personne, offreur, [], prescripteur_par_defaut=prescripteur)
    assert not NotificationPrescripteur.objects.exists()

    services.accorder(personne, offreur, [catalogue.INFORMER_PRESCRIPTEUR], prescripteur_par_defaut=prescripteur)
    services.accorder(personne, offreur, [catalogue.INFORMER_PRESCRIPTEUR], prescripteur_par_defaut=prescripteur)
    assert NotificationPrescripteur.objects.filter(prescripteur=prescripteur).count() == 1


@override_settings(DEBUG=True)
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

    # The prescriber who sent the orientation is notified
    client.force_login(PrescriberMembershipFactory(organization=prescripteur).user)
    response = client.get(reverse("inclusion_pass:prescripteur_notifications"))
    assertContains(response, f"<td>{personne.get_inverted_full_name()}</td>")


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
    "url_name", ["inclusion_pass:demandes_recues", "inclusion_pass:usagers", "inclusion_pass:presentation"]
)
def test_pages_offreur_refusees_aux_autres_professionnels(client, url_name):
    client.force_login(CompanyMembershipFactory().user)

    assert client.get(reverse(url_name)).status_code == 403
