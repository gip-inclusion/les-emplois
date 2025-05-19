import freezegun
import pytest
from django.core import management
from django.core.cache import caches
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.metabase.management.commands import metabase_data
from itou.metabase.models import DatumKey
from itou.users.models import User
from tests.users.factories import JobSeekerUserFactory


@pytest.fixture(name="command")
def command_fixture(mocker, settings):
    settings.METABASE_API_KEY = "metabase-api-key"
    command = metabase_data.Command()

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

    return command


@pytest.mark.parametrize("wet_run", [True, False])
def test_fetch(caplog, capsys, snapshot, command, wet_run):
    with freezegun.freeze_time("2024-11-20"):
        command.fetch_kpi(wet_run=wet_run)
    assert caches[command.CACHE_NAME].get_many(DatumKey) == snapshot(name="cache")
    assert capsys.readouterr() == snapshot(name="stdout and stderr")
    assert caplog.record_tuples == snapshot(name="logs")


def test_show(capsys, snapshot, command):
    caches[command.CACHE_NAME].set_many({key: f"The value of '{key.value}'" for key in DatumKey})

    command.show_kpi(wet_run=None)
    assert capsys.readouterr() == snapshot(name="stdout and stderr")


@pytest.mark.parametrize("wet_run", [True, False])
def test_fetch_stalled_job_seekers(caplog, mocker, snapshot, settings, wet_run):
    settings.METABASE_API_KEY = "metabase-api-key"

    entering_job_seeker = JobSeekerUserFactory(jobseeker_profile__is_stalled=False)
    exiting_job_seeker = JobSeekerUserFactory(jobseeker_profile__is_stalled=True)
    noop_job_seeker = JobSeekerUserFactory(jobseeker_profile__is_stalled=True)
    mocker.patch(
        "itou.utils.apis.metabase.Client.fetch_card_results",
        return_value=[
            {"ID": entering_job_seeker.pk},
            {"ID": noop_job_seeker.pk},
        ],
    )

    management.call_command("metabase_data", "stalled-job-seekers", wet_run=wet_run)
    if wet_run:
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=True),
            {entering_job_seeker, noop_job_seeker},
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=False), {exiting_job_seeker}, ordered=False
        )
    else:
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=True),
            {exiting_job_seeker, noop_job_seeker},
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(jobseeker_profile__is_stalled=False), {entering_job_seeker}, ordered=False
        )
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.metabase_data succeeded in "
    )
    assert caplog.messages[:-1] == snapshot(name="logs")
