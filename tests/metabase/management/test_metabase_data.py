import freezegun
import pytest
from django.core.cache import caches
from django.utils import timezone

from itou.metabase.management.commands import metabase_data
from itou.metabase.models import DatumKey


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
