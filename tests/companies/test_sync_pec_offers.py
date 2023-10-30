import pytest
from django.core import management
from django.test import override_settings

from itou.cities.models import City
from itou.companies.enums import POLE_EMPLOI_SIRET
from itou.companies.models import JobDescription
from itou.jobs.models import Appellation, Rome
from itou.utils.mocks.pole_emploi import API_OFFRES


@override_settings(
    API_ESD={
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
@pytest.mark.django_db(transaction=True)
def test_sync_pec_offers(capsys, respx_mock, monkeypatch):
    city = City.objects.create(
        slug="slug",
        department="89",
        name="Ville cool",
        post_codes=["31320"],
        code_insee="39478",
        coords=None,
    )
    rome = Rome(code="I1304")
    rome.save()
    appellation = Appellation.objects.create(
        code="I13042",
        # note the slight change in "industriel", fuzzy find will find it
        name="Technicien / Technicienne de maintenance industriel",
        rome=rome,
    )
    respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
        200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
    )
    base_url = "https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT"
    respx_mock.get(f"{base_url}&range=0-149").respond(206, json={"resultats": API_OFFRES})
    respx_mock.get(f"{base_url}&range=150-299").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=300-449").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=450-599").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=600-749").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=750-899").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=900-1049").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=1050-1149").respond(204)

    management.call_command("sync_pec_offers", wet_run=True, delay=0)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "retrieved count=2 PEC offers from PE API",
        "retrieved count=0 PEC offers from PE API",
        "! no appellation match found (rome_code='M1607' "
        "appellation_label='Secrétaire') skipping source_id='OHNOES'",
        "> successfully created count=1 PE job offers",
        "> successfully updated count=0 PE job offers",
        "> successfully deleted count=0 PE job offers",
    ]

    job_description = JobDescription.objects.get()
    assert job_description.custom_name == "Mécanicien de maintenance (F/H)."
    assert job_description.location == city
    assert job_description.appellation == appellation
    assert job_description.description == "Sous la responsabilité, vous avez une mission"
    assert job_description.market_context_description == "RANDSTAD"
    assert job_description.source_kind == "PE_API"
    assert job_description.source_url == "https://candidat.pole-emploi.fr/offres/recherche/detail/FOOBAR"
    assert job_description.source_id == "FOOBAR"
    assert job_description.siae.siret == POLE_EMPLOI_SIRET
    assert job_description.contract_type == "PERMANENT"
    assert job_description.other_contract_type == "Contrat à durée indéterminée"
    assert job_description.contract_nature == "PEC_OFFER"

    # test the update
    monkeypatch.setitem(API_OFFRES[0], "intitule", "NOUVEAU INTITULE")
    respx_mock.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-149").respond(
        206,
        json={"resultats": API_OFFRES},
    )
    management.call_command("sync_pec_offers", wet_run=True, delay=0)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines()[-3:] == [
        "> successfully created count=0 PE job offers",
        "> successfully updated count=1 PE job offers",
        "> successfully deleted count=0 PE job offers",
    ]
    job_description.refresh_from_db()
    assert job_description.custom_name == "NOUVEAU INTITULE"

    # test the deletion
    respx_mock.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-149").respond(
        206,
        json={"resultats": []},
    )
    management.call_command("sync_pec_offers", wet_run=True, delay=0)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines()[-3:] == [
        "> successfully created count=0 PE job offers",
        "> successfully updated count=0 PE job offers",
        "> successfully deleted count=1 PE job offers",
    ]
    assert JobDescription.objects.count() == 0
