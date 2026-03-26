import json
import pathlib
from operator import attrgetter

import pytest
from django.core.management import call_command
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertQuerySetEqual

from itou.insertion.models import GenericReferenceItem, GenericReferenceItemKind, Service, Structure
from itou.utils import constants as global_constants


@pytest.fixture(name="apis_mocks")
def apis_mocks_fixture(settings, respx_mock):
    mocks_dir = pathlib.Path(__file__).parent.joinpath("api_mocks")

    # data·inclusion API
    di_mocks_dir = mocks_dir.joinpath("data_inclusion")
    for file in di_mocks_dir.glob("**/*.json"):
        api_path = str(file.relative_to(di_mocks_dir)).replace(".json", "")
        respx_mock.get(f"{global_constants.API_DATA_INCLUSION_BASE_URL}/api/v1/{api_path}").respond(
            200, json=json.loads(file.read_text())
        )

    # DORA API
    settings.DORA_API_BASE_URL = "https://dora-api"
    dora_mocks_dir = mocks_dir.joinpath("dora")
    for file in dora_mocks_dir.glob("**/*.json"):
        api_path = str(file.relative_to(dora_mocks_dir)).replace(".json", "")
        respx_mock.get(f"{settings.DORA_API_BASE_URL}/api/emplois/{api_path}/").respond(
            200, json=json.loads(file.read_text())
        )


def test_full_import_wet_run(caplog, snapshot, apis_mocks):
    with assertSnapshotQueries(snapshot(name="SQL queries")):
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
    assert set(GenericReferenceItem.objects.all().values_list("kind", flat=True)) == {
        e.value for e in GenericReferenceItemKind
    }

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.insertion.management.commands.import_structures_and_services succeeded in"
    )


def test_full_import_dry_run(caplog, snapshot, apis_mocks):
    call_command("import_structures_and_services")  # Not specifying `wet_run=False` to also test default value

    assert Structure.objects.count() == 0
    assert Service.objects.count() == 0
    assert GenericReferenceItem.objects.count() == 0

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.insertion.management.commands.import_structures_and_services succeeded in"
    )


def test_full_import_idempotence(caplog, snapshot, apis_mocks):
    call_command("import_structures_and_services", wet_run=True)
    expected = {
        "Structure": Structure.objects.in_bulk(),
        "Service": Service.objects.in_bulk(),
        "GenericReferenceItem": GenericReferenceItem.objects.in_bulk(),
    }
    caplog.clear()

    call_command("import_structures_and_services", wet_run=True)
    assert {
        "Structure": Structure.objects.in_bulk(),
        "Service": Service.objects.in_bulk(),
        "GenericReferenceItem": GenericReferenceItem.objects.in_bulk(),
    } == expected

    assert caplog.messages[:-1] == snapshot(name="logs")
    assert caplog.messages[-1].startswith(
        "Management command itou.insertion.management.commands.import_structures_and_services succeeded in"
    )
