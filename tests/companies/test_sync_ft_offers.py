import pytest
from django.core import management

from itou.cities.models import City
from itou.companies.enums import POLE_EMPLOI_SIRET
from itou.companies.models import JobDescription
from itou.jobs.models import Appellation, Rome
from itou.utils.apis import pe_api_enums
from itou.utils.mocks.pole_emploi import API_OFFRES


@pytest.mark.django_db(transaction=True)
def test_sync_ft_offers(caplog, respx_mock):
    PEC_OFFERS = [
        {**offer, "natureContrat": pe_api_enums.NATURE_CONTRATS[pe_api_enums.NATURE_CONTRAT_PEC]}
        for offer in API_OFFRES
    ]
    EA_OFFERS = [{**offer, "id": offer["id"][::-1], "entrepriseAdaptee": True} for offer in API_OFFRES]

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
    respx_mock.get(f"{base_url}&range=0-149").respond(206, json={"resultats": PEC_OFFERS})
    respx_mock.get(f"{base_url}&range=150-299").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=300-449").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=450-599").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=600-749").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=750-899").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=900-1049").respond(206, json={"resultats": []})
    respx_mock.get(f"{base_url}&range=1050-1149").respond(204)

    ea_base_url = "https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=&entreprisesAdaptees=true"
    respx_mock.get(f"{ea_base_url}&range=0-149").respond(206, json={"resultats": EA_OFFERS})
    respx_mock.get(f"{ea_base_url}&range=150-299").respond(206, json={"resultats": []})

    management.call_command("sync_ft_offers", wet_run=True, delay=0)
    assert caplog.messages[-1].startswith(
        "Management command itou.companies.management.commands.sync_ft_offers succeeded in "
    )
    assert [message for message in caplog.messages[:-1] if not message.startswith("HTTP Request")] == [
        "retrieved count=2 offers from FT API",
        "retrieved count=0 offers from FT API",
        "retrieved count=2 PEC offers from FT API",
        "retrieved count=2 offers from FT API",
        "retrieved count=0 offers from FT API",
        "retrieved count=2 EA offers from FT API",
        "retrieved count=4 unique offers from FT API",
        "no appellation match found (rome_code='M1607' appellation_label='Secrétaire') skipping source_id='OHNOES'",
        "no appellation match found (rome_code='M1607' appellation_label='Secrétaire') skipping source_id='SEONHO'",
        "successfully created count=2 PE job offers",
        "successfully updated count=0 PE job offers",
        "successfully deleted count=0 PE job offers",
    ]

    [pec_job_description, ea_job_description] = JobDescription.objects.order_by("source_id").all()
    assert pec_job_description.custom_name == "Mécanicien de maintenance (F/H)."
    assert pec_job_description.location == city
    assert pec_job_description.appellation == appellation
    assert pec_job_description.description == "Sous la responsabilité, vous avez une mission"
    assert pec_job_description.market_context_description == "RANDSTAD"
    assert pec_job_description.source_kind == "PE_API"
    assert pec_job_description.source_url == "https://candidat.pole-emploi.fr/offres/recherche/detail/FOOBAR"
    assert pec_job_description.source_id == "FOOBAR"
    assert pec_job_description.source_tags == ["FT_PEC_OFFER"]
    assert pec_job_description.company.siret == POLE_EMPLOI_SIRET
    assert pec_job_description.contract_type == "PERMANENT"
    assert pec_job_description.other_contract_type == "Contrat à durée indéterminée"

    assert ea_job_description.custom_name == "Mécanicien de maintenance (F/H)."
    assert ea_job_description.location == city
    assert ea_job_description.appellation == appellation
    assert ea_job_description.description == "Sous la responsabilité, vous avez une mission"
    assert ea_job_description.market_context_description == "RANDSTAD"
    assert ea_job_description.source_kind == "PE_API"
    assert ea_job_description.source_url == "https://candidat.pole-emploi.fr/offres/recherche/detail/FOOBAR"
    assert ea_job_description.source_id == "RABOOF"
    assert ea_job_description.source_tags == ["FT_EA_OFFER"]
    assert ea_job_description.company.siret == POLE_EMPLOI_SIRET
    assert ea_job_description.contract_type == "PERMANENT"
    assert ea_job_description.other_contract_type == "Contrat à durée indéterminée"

    # test the update
    caplog.clear()
    PEC_OFFERS[0]["intitule"] = "NOUVEAU INTITULE"
    respx_mock.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-149").respond(
        206,
        json={"resultats": PEC_OFFERS},
    )
    management.call_command("sync_ft_offers", wet_run=True, delay=0)
    assert caplog.messages[-1].startswith(
        "Management command itou.companies.management.commands.sync_ft_offers succeeded in "
    )
    assert [message for message in caplog.messages[:-1] if not message.startswith("HTTP Request")] == [
        "retrieved count=2 offers from FT API",
        "retrieved count=0 offers from FT API",
        "retrieved count=2 PEC offers from FT API",
        "retrieved count=2 offers from FT API",
        "retrieved count=0 offers from FT API",
        "retrieved count=2 EA offers from FT API",
        "retrieved count=4 unique offers from FT API",
        "no appellation match found (rome_code='M1607' appellation_label='Secrétaire') skipping source_id='OHNOES'",
        "no appellation match found (rome_code='M1607' appellation_label='Secrétaire') skipping source_id='SEONHO'",
        "successfully created count=0 PE job offers",
        "successfully updated count=2 PE job offers",
        "successfully deleted count=0 PE job offers",
    ]
    pec_job_description.refresh_from_db()
    assert pec_job_description.custom_name == "NOUVEAU INTITULE"

    # test the deletion
    caplog.clear()
    respx_mock.get("https://pe.fake/offresdemploi/v2/offres/search?typeContrat=&natureContrat=FT&range=0-149").respond(
        206,
        json={"resultats": []},
    )
    management.call_command("sync_ft_offers", wet_run=True, delay=0)
    assert caplog.messages[-1].startswith(
        "Management command itou.companies.management.commands.sync_ft_offers succeeded in "
    )
    assert [message for message in caplog.messages[:-1] if not message.startswith("HTTP Request")] == [
        "retrieved count=0 offers from FT API",
        "retrieved count=0 PEC offers from FT API",
        "retrieved count=2 offers from FT API",
        "retrieved count=0 offers from FT API",
        "retrieved count=2 EA offers from FT API",
        "retrieved count=2 unique offers from FT API",
        "no appellation match found (rome_code='M1607' appellation_label='Secrétaire') skipping source_id='SEONHO'",
        "successfully created count=0 PE job offers",
        "successfully updated count=1 PE job offers",
        "successfully deleted count=1 PE job offers",
    ]
    assert JobDescription.objects.count() == 1
