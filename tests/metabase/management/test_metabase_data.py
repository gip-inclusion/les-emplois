import random

import freezegun
import pytest
from django.core.cache import caches
from django.core.management import call_command
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.metabase.management.commands import metabase_data
from itou.metabase.models import DatumKey
from itou.users.models import User
from tests.users.factories import JobSeekerFactory


@pytest.fixture()
def command_setup(mocker, settings):
    settings.METABASE_API_KEY = "metabase-api-key"

    def card_results(card, *args, **kwargs):
        if card == 272:
            return [{"Date Mise À Jour Metabase": timezone.now().isoformat()}]
        elif card == 4413:
            return [{"Département": "Département", "Région": "Région", "Valeurs distinctes de ID": card}]
        elif card == 1175:
            return [
                {
                    "Département Structure": "Département Structure",
                    "Région Structure": "Région Structure",
                    "Nombre de fiches de poste en difficulté de recrutement": card,
                }
            ]
        elif card == 5292:
            return [
                {
                    "Département Structure": "Département Structure",
                    "Région Structure": "Région Structure",
                    "% embauches en auto-prescription": card,
                }
            ]

    mocker.patch("itou.utils.apis.metabase.Client.fetch_card_results", side_effect=card_results)


@pytest.mark.parametrize("wet_run", [True, False])
@pytest.mark.usefixtures("command_setup")
def test_fetch_kpi(caplog, capsys, snapshot, django_capture_on_commit_callbacks, wet_run):
    with django_capture_on_commit_callbacks(execute=True), freezegun.freeze_time("2024-11-20"):
        call_command("metabase_data", "kpi", "fetch", wet_run=wet_run)
    assert caches[metabase_data.Command.CACHE_NAME].get_many(DatumKey) == snapshot(name="cache")
    assert capsys.readouterr() == snapshot(name="stdout and stderr")
    duration_position = -2 if wet_run else -1
    record_tuples = caplog.record_tuples
    _logger, _level, msg = record_tuples[duration_position]
    assert msg.startswith("Management command itou.metabase.management.commands.metabase_data succeeded in ")
    del record_tuples[duration_position]
    assert record_tuples == snapshot(name="logs")


@pytest.mark.usefixtures("command_setup")
def test_show_kpi(capsys, snapshot):
    caches[metabase_data.Command.CACHE_NAME].set_many({key: f"The value of '{key.value}'" for key in DatumKey})

    call_command("metabase_data", "kpi", "show", wet_run=random.choice([True, False]))
    assert capsys.readouterr() == snapshot(name="stdout and stderr")


@pytest.mark.parametrize("wet_run", [True, False])
def test_fetch_stalled_job_seekers(caplog, mocker, snapshot, settings, wet_run):
    settings.METABASE_API_KEY = "metabase-api-key"

    entering_job_seeker = JobSeekerFactory(jobseeker_profile__is_stalled=False)
    entering_and_converging_job_seeker = JobSeekerFactory(
        jobseeker_profile__is_stalled=False, jobseeker_profile__is_not_stalled_anymore=False
    )
    entering_and_not_converging_job_seeker = JobSeekerFactory(
        jobseeker_profile__is_stalled=False, jobseeker_profile__is_not_stalled_anymore=True
    )
    exiting_job_seeker = JobSeekerFactory(jobseeker_profile__is_stalled=True)
    exiting_and_converging_job_seeker = JobSeekerFactory(
        jobseeker_profile__is_stalled=True, jobseeker_profile__is_not_stalled_anymore=True
    )
    exiting_and_not_converging_job_seeker = JobSeekerFactory(
        jobseeker_profile__is_stalled=True, jobseeker_profile__is_not_stalled_anymore=False
    )
    noop_job_seeker = JobSeekerFactory(jobseeker_profile__is_stalled=True)
    mocker.patch(
        "itou.utils.apis.metabase.Client.fetch_card_results",
        return_value=[
            {"ID": entering_job_seeker.pk},
            {"ID": entering_and_converging_job_seeker.pk},
            {"ID": entering_and_not_converging_job_seeker.pk},
            {"ID": noop_job_seeker.pk},
        ],
    )

    call_command("metabase_data", "stalled-job-seekers", wet_run=wet_run)
    if wet_run:
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=True),
            {
                entering_job_seeker,
                entering_and_converging_job_seeker,
                entering_and_not_converging_job_seeker,
                noop_job_seeker,
            },
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=False),
            {exiting_job_seeker, exiting_and_converging_job_seeker, exiting_and_not_converging_job_seeker},
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_not_stalled_anymore=True),
            {entering_and_not_converging_job_seeker},
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_not_stalled_anymore=False),
            {exiting_and_not_converging_job_seeker},
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_not_stalled_anymore=None),
            {
                entering_job_seeker,
                entering_and_converging_job_seeker,
                exiting_job_seeker,
                exiting_and_converging_job_seeker,
                noop_job_seeker,
            },
            ordered=False,
        )
    else:
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=True),
            {
                exiting_job_seeker,
                exiting_and_converging_job_seeker,
                exiting_and_not_converging_job_seeker,
                noop_job_seeker,
            },
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=False),
            {entering_job_seeker, entering_and_converging_job_seeker, entering_and_not_converging_job_seeker},
            ordered=False,
        )
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.metabase_data succeeded in "
    )
    assert caplog.messages[:-1] == snapshot(name="logs")
