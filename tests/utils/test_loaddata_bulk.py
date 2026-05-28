import tempfile
from unittest.mock import call

import pytest
from django.core.management import call_command
from django.core.serializers import serialize
from pytest_django.asserts import assertQuerySetEqual

from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    SiaeConventionFactory,
)
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory


FIXTURE_SIZE = 3


def get_test_data(factory):
    model = factory._meta.model
    factory.create_batch(FIXTURE_SIZE)
    objects = list(model.objects.all())
    json_data = serialize("json-no-auto-fields", objects)
    # remove the objects to recreate them with through the fixture
    model.objects.all().delete()

    return model, objects, json_data


@pytest.mark.parametrize(
    "factory",
    [
        JobSeekerFactory,
        JobSeekerProfileFactory,
        CompanyFactory,
        SiaeConventionFactory,
        CompanyMembershipFactory,
        PrescriberFactory,
        PrescriberMembershipFactory,
        PrescriberOrganizationFactory,
        InstitutionFactory,
        InstitutionMembershipFactory,
    ],
)
def test_loaddata_bulk(factory):
    model, objects, json_data = get_test_data(factory)

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as file:
        file.write(json_data)
        file.seek(0)
        call_command("loaddata_bulk", file.name)
        assertQuerySetEqual(model.objects.all(), objects, ordered=False)


def test_loaddata_bulk_calls_bulk_create(mocker):
    _, objects, json_data = get_test_data(JobSeekerFactory)

    bulk_create_mock = mocker.patch("django.db.models.query.QuerySet.bulk_create")
    mocker.patch("itou.utils.management.commands.loaddata_bulk.Command.BATCH_SIZE", 1)

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as file:
        file.write(json_data)
        file.seek(0)
        call_command("loaddata_bulk", file.name)
        assert bulk_create_mock.call_count == FIXTURE_SIZE + 1
        calls = [call([obj]) for obj in objects]
        bulk_create_mock.assert_has_calls(calls)
