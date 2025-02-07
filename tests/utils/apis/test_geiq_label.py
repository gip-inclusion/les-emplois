import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.utils.apis import geiq_label


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


def test_improperly_configured(settings):
    settings.API_GEIQ_LABEL_TOKEN = ""
    with pytest.raises(ImproperlyConfigured):
        geiq_label.get_client()


def test_error_response(respx_mock, label_settings):
    client = geiq_label.get_client()

    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(400)
    with pytest.raises(geiq_label.LabelAPIError):
        client.get_all_geiq()

    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(
        200, json={"status": "Error"}
    )
    with pytest.raises(geiq_label.LabelAPIError):
        client.get_all_geiq()

    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(
        200,
        content="These aren't the droids you're looking for",
    )
    with pytest.raises(geiq_label.LabelAPIError):
        client.get_all_geiq()


def test_get_all_geiq_empty(respx_mock, label_settings):
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(
        200, json={"status": "Success", "result": []}
    )

    client = geiq_label.get_client()
    assert client.get_all_geiq() == []


def test_get_all_geiq(respx_mock, label_settings):
    expected_data = [{"id": nb, "nom": f"GEIQ N° {nb}"} for nb in range(1, 102)]
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=1").respond(
        200, json={"status": "Success", "result": expected_data[:100]}
    )
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/Geiq?sort=geiq.id&n=100&p=2").respond(
        200, json={"status": "Success", "result": expected_data[100:]}
    )

    client = geiq_label.get_client()
    assert client.get_all_geiq() == expected_data


def test_get_all_contracts_empty(respx_mock, label_settings):
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat?join=salariecontrat.salarie,s&where=s.geiq,=,123&count=true"
    ).respond(200, json={"status": "Success", "result": 0})
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat?join=salariecontrat.salarie,s&where=s.geiq,=,123&sort=salariecontrat.id&n=100&p=1"
    ).respond(200, json={"status": "Success", "result": []})
    client = geiq_label.get_client()
    assert client.get_all_contracts(123) == []


def test_get_all_contracts(respx_mock, label_settings):
    expected_data = [
        {"id": nb, "antenne": {}, "salarie": {"id": nb * 11, "nom": f"Salarie du contrat {nb}"}} for nb in range(1, 91)
    ]
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat?join=salariecontrat.salarie,s&where=s.geiq,=,123&count=true"
    ).respond(200, json={"status": "Success", "result": 90})
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat?join=salariecontrat.salarie,s&where=s.geiq,=,123&sort=salariecontrat.id&n=100&p=1"
    ).respond(200, json={"status": "Success", "result": expected_data})

    client = geiq_label.get_client()
    assert client.get_all_contracts(123) == expected_data


def test_get_all_prequalifications_empty(respx_mock, label_settings):
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification?join=salarieprequalification.salarie,s&where=s.geiq,=,123&count=true"
    ).respond(200, json={"status": "Success", "result": 0})
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification?join=salarieprequalification.salarie,s&where=s.geiq,=,123&sort=salarieprequalification.id&n=100&p=1"
    ).respond(200, json={"status": "Success", "result": []})
    client = geiq_label.get_client()
    assert client.get_all_prequalifications(123) == []


def test_get_all_prequalifications(respx_mock, label_settings):
    expected_data = [
        {
            "id": nb,
            "salarie": {"id": nb * 11, "nom": f"Salarie de la prequalification {nb}"},
            "action_pre_qualification": {"id": 3, "libelle": "POE", "libelle_abr": "POE"},
        }
        for nb in range(1, 10)
    ]
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification?join=salarieprequalification.salarie,s&where=s.geiq,=,123&count=true"
    ).respond(200, json={"status": "Success", "result": 9})
    respx_mock.get(
        f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification?join=salarieprequalification.salarie,s&where=s.geiq,=,123&sort=salarieprequalification.id&n=100&p=1"
    ).respond(200, json={"status": "Success", "result": expected_data})

    client = geiq_label.get_client()
    assert client.get_all_prequalifications(123) == expected_data


def test_get_taux_geiq_single(respx_mock, label_settings):
    expected_data = [
        [
            {
                "geiq_id": 123,
                "taux_rupture_periode_essai": "",
                "taux_rupture_hors_periode_essai": "",
                "taux_sortie_emploi_durable": "50.0",
                "taux_sortie_emploi": "50.0",
                "taux_obtention_qualification": "75.0",
            }
        ]
    ]
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/TauxGeiq?where=geiq,=,123").respond(
        200, json={"status": "Success", "result": expected_data}
    )

    client = geiq_label.get_client()
    assert client.get_taux_geiq(geiq_id=123) == expected_data


def test_get_taux_geiq_batch(respx_mock, label_settings):
    expected_data = [
        [
            {
                "geiq_id": i,
                "taux_rupture_periode_essai": "",
                "taux_rupture_hors_periode_essai": "",
                "taux_sortie_emploi_durable": str(i % 100),
                "taux_sortie_emploi": str(2 * i % 100),
                "taux_obtention_qualification": str(3 * i % 100),
            }
            for i in range(102)
        ]
    ]
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/TauxGeiq?sort=geiq.id&n=100&p=1").respond(
        200, json={"status": "Success", "result": expected_data[:100]}
    )
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/TauxGeiq?sort=geiq.id&n=100&p=2").respond(
        200, json={"status": "Success", "result": expected_data[100:]}
    )

    client = geiq_label.get_client()
    assert client.get_taux_geiq() == expected_data


def test_get_synthese_pdf(respx_mock, label_settings):
    expected_data = b"some pdf file"
    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SynthesePDF?id=123").respond(
        200,
        content=expected_data,
        headers={
            "content-length": f"{len(expected_data)}",
            "content-transfer-encoding": "binary",
            "content-type": "application/pdf",
        },
    )

    client = geiq_label.get_client()
    assert client.get_synthese_pdf(geiq_id=123) == expected_data


def test_get_synthese_pdf_invalid_content_type(respx_mock, label_settings):
    client = geiq_label.get_client()

    respx_mock.get(f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SynthesePDF?id=123").respond(
        200,
        content=b"",
        headers={
            "content-length": "0",
            "content-transfer-encoding": "binary",
            "content-type": "text/html",
        },
    )
    with pytest.raises(geiq_label.LabelAPIError):
        assert client.get_synthese_pdf(geiq_id=123)
