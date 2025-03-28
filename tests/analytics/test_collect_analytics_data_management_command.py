import datetime
import unittest.mock

import pytest
from django.core.management import call_command
from django.db import models
from django.utils import timezone
from freezegun import freeze_time

from itou.analytics.management.commands import collect_analytics_data
from itou.analytics.models import Datum, DatumCode
from tests.analytics import factories


class CodeTest(models.TextChoices):
    CODE_001 = "CODE-001", "Premier code de test"
    CODE_002 = "CODE-002", "Second code de test"


@pytest.fixture(name="command")
def command_fixture(mocker):
    command = collect_analytics_data.Command()
    mocker.patch.object(command, "_get_data", return_value={})
    mocker.spy(command, "show_data")
    mocker.spy(command, "save_data")

    return command


@freeze_time("2022-01-01")
def test_handle_default_options(command, caplog):
    command.handle(save=False, offset=0)

    assert command._get_data.call_args_list == [
        unittest.mock.call(timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    ]
    assert command.show_data.call_args_list == [unittest.mock.call({})]
    assert command.save_data.call_args_list == []
    assert caplog.messages == [
        "Collecting analytics data before '2022-01-01 00:00:00+00:00'.",
        "Analytics data computed.",
    ]


@freeze_time()
def test_handle_save_option(command):
    command.handle(save=True, offset=0)

    assert command.save_data.call_args_list == [
        unittest.mock.call({}, timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))
    ]


@freeze_time("2022-01-01")
def test_handle_offset_option(command, caplog):
    command.handle(save=False, offset=7)

    assert caplog.messages == [
        "Collecting analytics data before '2021-12-25 00:00:00+00:00'.",
        "Analytics data computed.",
    ]


def test_show_data(command, caplog):
    command.show_data({CodeTest.CODE_001: 42, CodeTest.CODE_002: 21})

    assert caplog.messages == [
        "Premier code de test (CODE-001): 42",
        "Second code de test (CODE-002): 21",
    ]


def test_save_data(command, caplog):
    command.save_data(
        {CodeTest.CODE_001: 42, CodeTest.CODE_002: 21},
        datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC),
    )

    objects = Datum.objects.order_by("code").all()
    assert len(objects) == 2
    assert objects[0].code == CodeTest.CODE_001
    assert objects[0].value == 42
    assert objects[1].code == CodeTest.CODE_002
    assert objects[1].value == 21
    assert caplog.messages == [
        "Saving analytics data in bucket '2021-12-31'.",
        "Successfully saved code=CODE-001 bucket=2021-12-31 value=42.",
        "Successfully saved code=CODE-002 bucket=2021-12-31 value=21.",
    ]


def test_save_data_with_an_integrity_error(command, caplog):
    factories.DatumFactory(code=CodeTest.CODE_001, bucket="2021-12-31")

    command.save_data(
        {CodeTest.CODE_001: 42, CodeTest.CODE_002: 21},
        datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC),
    )

    objects = Datum.objects.order_by("code").all()
    assert len(objects) == 2
    assert objects[1].code == CodeTest.CODE_002
    assert objects[1].value == 21
    assert caplog.messages == [
        "Saving analytics data in bucket '2021-12-31'.",
        "Failed to save code=CODE-001 for bucket=2021-12-31 because it already exists.",
        "Successfully saved code=CODE-002 bucket=2021-12-31 value=21.",
    ]


def test_save_data_with_a_float(command, caplog):
    command.save_data(
        {CodeTest.CODE_001: 42.5, CodeTest.CODE_002: 21},
        datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC),
    )
    objects = Datum.objects.order_by("code").all()
    assert len(objects) == 1
    assert objects[0].code == CodeTest.CODE_002
    assert objects[0].value == 21
    assert caplog.messages == [
        "Saving analytics data in bucket '2021-12-31'.",
        "Failed to save code=CODE-001 for bucket=2021-12-31 because of a ValidationError: 42.5 is not an integer.",
        "Successfully saved code=CODE-002 bucket=2021-12-31 value=21.",
    ]


@freeze_time("2024-12-03")
def test_management_command_name_and_that_all_codes_are_saved(
    datadog_client, sentry_respx_mock, updown_respx_mock, github_respx_mock
):
    call_command("collect_analytics_data", save=True)

    assert Datum.objects.all().count() == len(DatumCode)
