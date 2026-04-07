import json
import pathlib
from operator import attrgetter

import pytest
from django.core.management import call_command
from pytest_django.asserts import assertQuerySetEqual

from itou.dora.models import ReferenceDatum, ReferenceDatumKind, Service, Structure
from itou.utils import constants as global_constants


@pytest.fixture(name="apis_mocks")
def apis_mocks_fixture(settings, respx_mock):
    # data·inclusion API
    mocks_dir = pathlib.Path(__file__).parent.joinpath("api_mocks")
    for file in mocks_dir.glob("**/*.json"):
        api_path = str(file.relative_to(mocks_dir)).replace(".json", "")
        respx_mock.get(f"{global_constants.API_DATA_INCLUSION_BASE_URL}/api/v1/{api_path}").respond(
            200, json=json.loads(file.read_text())
        )

    # DORA API
    settings.DORA_API_BASE_URL = "https://dora-api"
    respx_mock.get(settings.DORA_API_BASE_URL + "/api/emplois/services/").respond(
        200,
        json=[
            {
                "id": "46f7ea19-c97b-4f45-90a9-027b44cad927",
                "short_desc": "Les emplois de l'inclusion est un service numérique de mise en relation d'employeurs solidaires avec des candidats éloignés de l'emploi par le biais de tiers (prescripteurs habilités, orienteurs) ou en auto-prescription.",  # noqa: E501
                "funding_labels": [],
                "forms_info": [
                    {
                        "name": "cc4e1fbc-533b-46e2-8b33-bc31c33c9ffd/2025-03-13_15h35_21.png",
                        "url": "http://dora.url/cc4e1fbc-533b-46e2-8b33-bc31c33c9ffd/2025-03-13_15h35_21.png",
                    },
                    {
                        "name": "cc4e1fbc-533b-46e2-8b33-bc31c33c9ffd/2025-03-13_15h34_58.png",
                        "url": "http://dora.url/cc4e1fbc-533b-46e2-8b33-bc31c33c9ffd/2025-03-13_15h34_58.png",
                    },
                ],
                "online_form": "",
                "credentials": ["Contrat d'apprentissage", "Curriculum vitæ"],
                "is_orientable_with_form": True,
                "average_orientation_response_delay_days": 16,
            },
            {
                "id": "b6f651e2-56d7-4ffa-a1c6-ae7295089a9e",
                "short_desc": "Immersion Facilitée donne accès à des entreprises qui accueillent en immersion et simplifie les démarches de conventionnement de l'immersion.",  # noqa: E501
                "funding_labels": [],
                "forms_info": [],
                "online_form": "https://example.fr",
                "credentials": ["3 derniers avis d'imposition"],
                "is_orientable_with_form": False,
                "average_orientation_response_delay_days": None,
            },
        ],
    )
    respx_mock.get(settings.DORA_API_BASE_URL + "/api/emplois/disabled-dora-form-di-structures/").respond(
        200,
        json=[
            {"source": "emplois-de-linclusion", "structure_id": "null"},
            {"source": "emplois-de-linclusion", "structure_id": "empty"},
        ],
    )


def test_full_import_wet_run(caplog, snapshot, apis_mocks):
    call_command("import_structures_and_services", wet_run=True)

    assertQuerySetEqual(
        Structure.objects.all(),
        ["emplois-de-linclusion--null", "emplois-de-linclusion--empty", "dora--cc4e1fbc-533b-46e2-8b33-bc31c33c9ffd"],
        transform=attrgetter("uid"),
        ordered=False,
    )
    assertQuerySetEqual(
        Service.objects.all(),
        [
            "emplois-de-linclusion--null",
            "emplois-de-linclusion--empty",
            "dora--46f7ea19-c97b-4f45-90a9-027b44cad927",
            "dora--b6f651e2-56d7-4ffa-a1c6-ae7295089a9e",
        ],
        transform=attrgetter("uid"),
        ordered=False,
    )
    assert set(ReferenceDatum.objects.all().values_list("kind", flat=True)) == {e.value for e in ReferenceDatumKind}

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.dora.management.commands.import_structures_and_services succeeded in"
    )


def test_full_import_dry_run(caplog, snapshot, apis_mocks):
    call_command("import_structures_and_services")  # Not specifying `wet_run=False` to also test default value

    assert Structure.objects.count() == 0
    assert Service.objects.count() == 0
    assert ReferenceDatum.objects.count() == 0

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.dora.management.commands.import_structures_and_services succeeded in"
    )


def test_full_import_idempotence(caplog, snapshot, apis_mocks):
    call_command("import_structures_and_services", wet_run=True)
    expected = {
        "Structure": Structure.objects.count(),
        "Service": Service.objects.count(),
        "ReferenceDatum": ReferenceDatum.objects.count(),
    }
    caplog.clear()

    call_command("import_structures_and_services", wet_run=True)
    assert {
        "Structure": Structure.objects.count(),
        "Service": Service.objects.count(),
        "ReferenceDatum": ReferenceDatum.objects.count(),
    } == expected

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.dora.management.commands.import_structures_and_services succeeded in"
    )
